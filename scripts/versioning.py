import re
import subprocess
from enum import Enum
from typing import Optional

import toml
import utilities
from pydantic import BaseModel
from typer import Exit, Option, Typer, secho
from utilities import __version__ as py_version

version_regex = r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:[\+\-]([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
app = Typer()


class BumpType(str, Enum):
    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"


def get_most_recent_tag():
    tag = subprocess.check_output(["git", "describe", "--tags"]).decode("utf-8").strip()
    version = Version.parse(tag)
    if version.prerelease:
        version.prerelease = f"post.{version.prerelease}"
    return version


class Version(BaseModel):
    major: int
    minor: int
    patch: int
    prerelease: Optional[str] = ""
    metadata: Optional[str] = ""

    @classmethod
    def parse(cls, version_str) -> "Version":
        """Parse a version str into a Version Object."""
        if version_str.startswith("v"):
            raise ValueError(
                f"Version starts with 'v' please remove it before proceeding: {version_str}"
            )
        match = re.match(version_regex, version_str)
        if not match:
            raise ValueError(f"Unknown version string: {version_str}")
        major, minor, patch, prerelease, metadata = match.groups()
        return cls(
            major=major,
            minor=minor,
            patch=patch,
            prerelease=prerelease,
            metadata=metadata,
        )

    def __str__(self) -> str:
        """Get string representation of the version object."""
        output = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            output += f"-{self.prerelease}"
        if self.metadata:
            output += f"+{self.metadata}"
        return output

    def __lt__(self, other) -> bool:
        if not isinstance(other, Version):
            raise TypeError(f"Can't compare type {type(other)} to type Version.")
        return str(self) < str(other)

    def bump(
        self, bump_type: BumpType = BumpType.PATCH, clear_extras: bool = False
    ) -> "Version":
        """Bump the version of the Version object."""
        out = self.copy()
        if bump_type == BumpType.MAJOR:
            out.major += 1
        elif bump_type == BumpType.MINOR:
            out.minor += 1
        elif bump_type == BumpType.PATCH:
            out.patch += 1
        else:
            raise ValueError(f"unknown bump_type {bump_type}")
        if clear_extras:
            out.metadata = ""
            out.prerelease = ""
        return out


def get_current_version():
    "Get current version of project."
    poetry_version = toml.load("pyproject.toml")["tool"]["poetry"]["version"]
    if poetry_version != py_version:
        raise ValueError(
            f"Python and Poetry version do not match please correct this manually\n"
            f"Python Version: {py_version}\n"
            f"Poetry Version: {poetry_version}"
        )
    return Version.parse(py_version)


def write_new_version(
    version: Version,
    init_file: str,
    version_pattern: str = r"^__version__\s*=\s*\"(.*)\"",
) -> None:
    """Write the new version to the set files."""
    version_pattern = r"^__version__\s*=\s*\"(.*)\""
    with open(init_file) as f:
        contents = f.read()
        new_contents = re.sub(
            version_pattern, f'__version__ = "{version}"', contents, flags=re.MULTILINE
        )
    with open(init_file, "w") as f:
        f.write(new_contents)

    old_toml = toml.load("pyproject.toml")
    old_toml["tool"]["poetry"]["version"] = str(version)
    with open("pyproject.toml", "w") as f:
        f.write(toml.dumps(old_toml))


def validate(tagged_version: Version, current_version: Version):
    if tagged_version.prerelease is not None and current_version != tagged_version:
        return False
    return True


@app.command("validate")
def run_validate():
    tagged_version = get_most_recent_tag()
    curr_version = get_current_version()
    if not validate(tagged_version, curr_version):
        secho(
            "Detected tag on this version but tagged version and current version do not match.\n"
            f"Tagged Version: {tagged_version}\n"
            f"Current Version: {curr_version}"
        )
        raise Exit(2)
    return 0


@app.command("tag")
def tag(force: bool = Option(False, "--force")):
    tagged_version = get_most_recent_tag()
    current_version = get_current_version()
    if validate(tagged_version, current_version):
        secho("Tag already matches current version")
        return 0
    if current_version.prerelease or current_version.metadata:
        secho("Can't tag prereleases or metadata yet without --force")
        raise Exit(2)
    tag_output = (
        subprocess.check_output(["git", "tag", str(current_version)])
        .decode("utf-8")
        .strip()
    )
    if tag_output:
        print(tag_output)
    else:
        secho("success!")
    return 0


@app.command("set")
def set_version(
    new_version: str = Option(None, "--version"),
    bump_type: BumpType = Option(None, "--bump"),
    prerelease: Optional[str] = Option(None, "--prerelease", "-p"),
    metadata: Optional[str] = Option(None, "--metadata", "-m"),
    overwrite: bool = Option(
        False,
        "--overwrite",
        "-o",
        help="Overwrite the values in pyproject.toml and __init__.py",
    ),
    force: bool = Option(
        False,
        "--force",
        "-f",
        help="Clear the current metadata and prerelease information.",
    ),
    clear: bool = Option(
        False,
        "--clear",
        "-c",
        help="Clear the current metadata and prerelease information.",
    ),
    short: bool = Option(
        False,
        "--short",
        "-s",
        help=" -s.",
    ),
):
    # If version is explicitly passed in override current version
    curr_version = get_current_version()
    if new_version:
        if new_version == "git":
            version = get_most_recent_tag()
        else:
            version = Version.parse(new_version)
            if version < curr_version and not force:
                secho(
                    "Version you are setting is less than current version. Please use --force flag to force this change."
                )
                raise Exit(2)
    else:
        version = curr_version
    # Bump the version with the corresponding CLI arg
    if bump_type:
        version = version.bump(bump_type=bump_type, clear_extras=clear)
    # If we are adding prerelease/metadata information make sure we are not overwriting unless explictly set
    if prerelease is not None or metadata is not None:
        if (version.prerelease is None and version.metadata is None) or force:
            version.prerelease = prerelease
            version.metadata = metadata
        else:
            secho(
                "Current version has metadata or prerelease information that you are trying to replace, please use the --force to force"
            )
            raise Exit(2)
    if overwrite:
        write_new_version(version, utilities.__file__)
    if short:
        secho(version)
    else:
        secho(f"New version: {version}")
    return 0


@app.command("get")
def get_version():
    # If version is explicitly passed in override current version
    curr_version = get_current_version()
    print(curr_version)
    return 0


if __name__ == "__main__":
    app()
