"""
"""

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

import requests
from poetry.console.application import Application
from poetry.console.commands.command import Command
from poetry.core.factory import Factory
from poetry.core.masonry.utils.helpers import escape_name
from poetry.core.poetry import Poetry
from poetry.plugins.application_plugin import ApplicationPlugin


@dataclass
class GitHubRelease:
    uid: int = -1
    url: str = ""
    url_upload: str = ""


@dataclass
class GitRemote:
    name: str = ""
    url: str = ""
    repo_name: str = ""
    repo_owner: str = ""


class ReleaseCommand(Command):
    """ """

    name: str = "release"
    description: str = "Create a git tag and a GitHub release."

    _poetry: Poetry = Factory().create_poetry()

    def __find_git_remotes(self, lines: List[str]) -> List[GitRemote]:
        """ """

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
        self, remote: GitRemote, version: str, username: str, token: str
    ) -> Union[GitHubRelease, str]:
        """ """

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
            },
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
        """ """

        # Make sure that the provided asset does exist.
        if not os.path.exists(asset) or not os.path.isfile(asset):
            return "Provided asset file doesn't exist or isn't a file."

        # Upload asset.
        with open(asset, "rb") as file:
            data: bytes = file.read()
            response = requests.post(
                url=release.url_upload,
                auth=(username, token),
                params=[("name", os.path.basename(asset))],
                files={"file": ("file", data, "application/octet-stream")},
            )

        # If request wasn't successful, return an error.
        if response.status_code != 201:
            return f"Request failed with status code {response.status_code}:\n" + json.dumps(
                response.json(), indent=4
            ) + "\n" + str(response.request.headers)

    def __get_built_files(self, version: str) -> List[Path]:
        """ """

        dist = self._poetry.file.parent / "dist"
        wheels = list(dist.glob(f"{escape_name(self._poetry.package.pretty_name)}-{version}-*.whl"))
        tars = list(dist.glob(f"{self._poetry.package.pretty_name}-{version}.tar.gz"))

        return sorted(wheels + tars)

    def handle(self) -> int:
        """ """

        # Check if "version" field exists in the Poetry configuration.
        if "version" not in self._poetry.local_config:
            self.line("Missing 'version' field in configuration.")
            return 1

        # Get the version string.
        version: str = self._poetry.local_config["version"]
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
                "In order to authenticate with GitHub, a PAT needs to be specified through a 'GITHUB_TOKEN' environment variable."
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
            remote=remote, version="v" + version, username=github_username, token=github_token
        )
        if isinstance(github_release, str):
            self.line(github_release)
            return 5

        # Display successful release creation.
        self.line(f"Release v{version} created and accessable through the following URL:")
        self.line(f"  https://github.com/{remote.repo_owner}/{remote.repo_name}/releases/tag/v{version}")

        # Files to be uploaded as assets.
        files: List[Path] = self.__get_built_files(version)

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
    """ """

    return ReleaseCommand()


class GitHubReleasePlugin(ApplicationPlugin):
    """ """

    def activate(self, application: Application):
        """ """

        application.command_loader.register_factory(ReleaseCommand.name, factory)
