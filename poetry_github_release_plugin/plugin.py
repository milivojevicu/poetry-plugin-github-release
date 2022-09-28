"""
"""

import subprocess

from poetry.console.commands.command import Command
from poetry.console.application import Application
from poetry.plugins.application_plugin import ApplicationPlugin
from poetry.core.poetry import Poetry
from poetry.core.factory import Factory


class ReleaseCommand(Command):
    name: str = "release"
    _poetry: Poetry = Factory().create_poetry()

    def handle(self) -> int:
        if "version" not in self._poetry.local_config:
            self.line("Missing 'version' field in configuration.")
            return 1

        version: str = self._poetry.local_config["version"]

        result = subprocess.run(["git", "tag", version])

        return result.returncode


def factory() -> Command:
    return ReleaseCommand()


class GitHubReleasePlugin(ApplicationPlugin):
    def activate(self, application: Application):
        application.command_loader.register_factory(ReleaseCommand.name, factory)
