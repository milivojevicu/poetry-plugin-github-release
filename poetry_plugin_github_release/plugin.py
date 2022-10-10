"""
Poetry plugin and subcommand for creating GitHub releases.
"""

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

import requests
from cleo.helpers import option
from poetry.console.application import Application
from poetry.console.commands.command import Command
from poetry.core.factory import Factory
from poetry.core.masonry.utils.helpers import escape_name
from poetry.core.poetry import Poetry
from poetry.plugins.application_plugin import ApplicationPlugin


@dataclass
class GitHubRelease:
    """Represents an instance of a GitHub release."""

    uid: int = -1
    url: str = ""
    url_upload: str = ""


@dataclass
class GitRemote:
    """Represents an instance of a Git remote, read from the configuration."""

    name: str = ""
    url: str = ""
    repo_name: str = ""
    repo_owner: str = ""


class ReleaseCommand(Command):
    """A command for creating releases on GitHub (and Git tags)."""

    name: str = "release"
    description: str = "Create a git tag and a GitHub release."
    # arguments = [argument("cache", description="The name of the cache to clear.")]
    options = [option("--pre-release", "-p", description="Mark the release as a pre-release.")]

    _poetry: Poetry = Factory().create_poetry()

    def __find_git_remotes(self, lines: List[str]) -> List[GitRemote]:
        """
        Finds remotes in the Git configuration.

        :arg lines: Lines in the configuration file.

        :return: A list of Git remotes.
        """

        remote_pattern = re.compile(r'\[remote "([a-z]*)"\]\n')
        remotes: List[GitRemote] = []
        i = 0
        while i < len(lines):
            # Preprare data.
            line: str = lines[i]

            # Increment line index.
            i += 1

            # Look for the remote header.
            result = remote_pattern.match(line)
            if result is None:
                continue
            remote_name = result.group(1)

            # Collect URL under current header.
            remote_url: str = ""
            while not lines[i].startswith("["):
                if lines[i].strip().startswith("url = "):
                    remote_url = lines[i].split("=")[-1].strip()
                i += 1

            # If the remote URL was not found, skip.
            if len(remote_url) == 0:
                continue

            # Get repositry name and owner from the remote URL.
            if remote_url.startswith("git@"):
                # SSH URL
                remote_repo_owner = remote_url.split(":")[-1].split("/")[0]
                remote_repo_name = remote_url.split(":")[-1].split("/")[1]
            else:
                # HTTPS URL
                remote_repo_owner = remote_url.split("/")[-2]
                remote_repo_name = remote_url.split("/")[-1]

            # Remove .git from the repositry name if it exists.
            if remote_repo_name.endswith(".git"):
                remote_repo_name = remote_repo_name[:-4]

            # Add remote to list.
            remotes.append(
                GitRemote(
                    name=remote_name,
                    url=remote_url,
                    repo_name=remote_repo_name,
                    repo_owner=remote_repo_owner,
                )
            )

        return remotes

    def __github_create_release(
        self, remote: GitRemote, version: str, username: str, token: str, pre_release: bool
    ) -> Union[GitHubRelease, str]:
        """
        Creates a release on GitHub.

        :arg remote: A Git remote instance. The repository name and owner are read from here.
        :arg version: Version of the software being released.
        :arg username: GitHub username.
        :arg token: GitHub token.
        :arg pre_release: If this release should be a pre-release.

        :return: The created GitHub release object, or an error message if release creation was not
            successful.
        """

        # Construct the URL for the releases endpoint of GitHub API.
        github_api_releases = (
            f"https://api.github.com/repos/{remote.repo_owner}/{remote.repo_name}/releases"
        )

        # Post to create a new release. If the tag doesn't exist, it will be automatically created.
        response = requests.post(
            url=github_api_releases,
            auth=(username, token),
            json={
                "tag_name": version,
                "target_commitish": "main",
                "generate_release_notes": True,
                "prerelease": pre_release,
            },
            timeout=60,
        )

        # If request wasn't successful, return an error.
        if response.status_code != 201:
            return f"Request failed with status code {response.status_code}:\n" + json.dumps(
                response.json(), indent=4
            )

        # Prepare the `GitHubRelease` object.
        response_json = response.json()
        release = GitHubRelease(
            uid=int(response_json["id"]),
            url=response_json["url"],
            url_upload=response_json["upload_url"].split("{")[0],
        )

        return release

    def __github_upload_asset(
        self, asset: Path, release: GitHubRelease, username: str, token: str
    ) -> Optional[str]:
        """
        Upload assets to an existing GitHub release.

        :arg asset: Path to the asset.
        :arg release: GitHub release instance.
        :arg username: GitHub username.
        :arg token: GitHub token.

        :return: `None` on success, otherwise an error message.
        """

        # Make sure that the provided asset does exist.
        if not os.path.exists(asset) or not os.path.isfile(asset):
            return "Provided asset file doesn't exist or isn't a file."

        # Upload asset.
        with open(asset, "rb") as file:
            data: bytes = file.read()

        # Deterine the data type of the asset.
        content_type_bytes = "application/octet-stream"
        content_type = {
            ".gz": "application/gzip",
        }.get(os.path.splitext(asset)[-1], content_type_bytes)

        # Prepare asset data for upload. This makes the octet-stream data upload as
        # 'multipart/form-data'. GitHub API requires this, not sure why. And if other
        # data type, such as gzip, are uploaded the same way, they get corrupted; so
        # they are uploaded without multipart.
        kwargs = {}
        if content_type == content_type_bytes:
            kwargs["files"] = {"file": ("file", data, content_type)}
        else:
            kwargs["data"] = data
            kwargs["headers"] = {"Content-Type": content_type}

        # Post the file.
        response = requests.post(
            url=release.url_upload,
            auth=(username, token),
            params=[("name", os.path.basename(asset))],
            **kwargs,
            timeout=120,
        )

        # If request wasn't successful, return an error.
        if response.status_code != 201:
            return (
                f"Request failed with status code {response.status_code}:\n"
                + json.dumps(response.json(), indent=4)
                + "\n"
                + str(response.request.headers)
            )

    def __get_built_files(self, version: str) -> List[Path]:
        """
        Find files created by the `poetry build` command.

        :arg version: Version of the build to look for.

        :return: A list of paths to build output files.
        """

        dist = self._poetry.file.parent / "dist"
        wheels = list(dist.glob(f"{escape_name(self._poetry.package.pretty_name)}-{version}-*.whl"))
        tars = list(dist.glob(f"{self._poetry.package.pretty_name}-{version}.tar.gz"))

        return sorted(wheels + tars)

    def handle(self) -> int:
        """
        Comand entry point.

        :return: Status code.
        """

        # Check if "version" field exists in the Poetry configuration.
        if "version" not in self._poetry.local_config:
            self.line("Missing 'version' field in configuration.")
            return 1

        # Get the version string.
        version: str = self._poetry.local_config["version"]
        short_version: str = version
        if "-" in version:
            split_version = version.split("-")
            short_version = (
                split_version[0]
                + split_version[1][0]
                + "".join(char for char in split_version[1] if char.isnumeric())
            )
        # Get the root directory of project.
        project_root_path: str = os.path.split(self._poetry.file.path)[0]
        # Get the git configuration file in the project root.
        git_config_path: str = os.path.join(project_root_path, ".git/config")

        # Check if the git configuration file exists.
        if not os.path.exists(git_config_path):
            self.line("Working directory is not a git repository.")
            return 2

        # Get git remotes from the configuration
        with open(git_config_path, "r", encoding="UTF-8") as file:
            git_config_data = file.readlines()
        remotes: List[GitRemote] = self.__find_git_remotes(git_config_data)

        # Not git remotes in the configuration, no where to upload the release.
        if len(remotes) == 0:
            self.line("Found 0 git remotes.")
            return 3

        # Multiple git remotes currently not supported.
        if len(remotes) > 1:
            self.line("Found multiple git remotes, which is currently not supported.")
            return 99

        # Get a single remote.
        # TODO: Should be replaced with a decision to pick one of multiple if there is multiple
        # and have the above error removed.
        remote: GitRemote = remotes[0]

        # Get a token from the environment.
        if "GITHUB_TOKEN" not in os.environ:
            self.line(
                "In order to authenticate with GitHub, a PAT needs to be specified through a"
                " 'GITHUB_TOKEN' environment variable."
            )
            return 4

        github_token = os.environ["GITHUB_TOKEN"]

        # Get the username from the git configuration.
        result = subprocess.run(
            ["git", "config", "user.username"], capture_output=True, check=False
        )
        github_username = result.stdout.decode().strip()

        # Create a git tag and a GitHub release.
        github_release = self.__github_create_release(
            remote=remote,
            version="v" + version,
            username=github_username,
            token=github_token,
            pre_release=self.option("pre-release", False),
        )
        if isinstance(github_release, str):
            self.line(github_release)
            return 5

        # Display successful release creation.
        self.line(f"Release v{version} created and accessable through the following URL:")
        self.line(
            f"  https://github.com/{remote.repo_owner}/{remote.repo_name}/releases/tag/v{version}"
        )

        # Files to be uploaded as assets.
        files: List[Path] = self.__get_built_files(short_version)

        if len(files) > 0:
            self.line(f"Attempting to attach {len(files)} asset(s) to the release.")

        for i, file in enumerate(files):
            self.write(f"  {i + 1}. Uploading '{os.path.basename(file)}'...")

            # Try to upload asset.
            result = self.__github_upload_asset(
                asset=file, release=github_release, username=github_username, token=github_token
            )

            # Upload failed.
            if result is not None:
                self.line(" Failed.")
                self.line(result)
                continue

            self.line(" Done.")

        return 0


def factory() -> Command:
    """
    Factory used for add the `release` subcommand instead of adding the subcommand directory.

    :return: A new instance of the `ReleaseCommand` class.
    """

    return ReleaseCommand()


class GitHubReleasePlugin(ApplicationPlugin):
    """Main plugin class."""

    def activate(self, application: Application):
        """
        This method is called by `poetry` to initialize the plugin.
        Used to add the `release` subcommand.

        :arg application: The command-line application this plugin is attached to.
        """

        # Add the subcommand by register a factory. This way is recommended instead of the
        # `application.add` method, as per `poetry` documentation:
        # https://python-poetry.org/docs/plugins/#application-plugins
        application.command_loader.register_factory(ReleaseCommand.name, factory)
