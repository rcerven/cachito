#!/usr/bin/env python3
import argparse
import datetime
import logging
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_NAME = Path(sys.argv[0]).name

DESCRIPTION = """\
Find build dependencies for all your runtime dependencies. The input to this
script must be a requirements.txt file containing all the *recursive* runtime
dependencies. You can use pip-compile to generate such a file. The output is an
intermediate file that must first go through pip-compile before being used in
a Cachito request.
"""

logging.basicConfig(format="%(levelname)s: %(message)s")

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


class FindBuilddepsError(Exception):
    """Failed to find build dependencies."""


def _pip_download(requirements_files, output_file, tmpdir, no_cache):
    """Run pip download, write output to file."""
    cmd = [
        "pip",
        "download",
        "-d",
        tmpdir,
        "--no-binary",
        ":all:",
        "--use-pep517",
        "--verbose",
    ]
    if no_cache:
        cmd.append("--no-cache-dir")
    for file in requirements_files:
        cmd.append("-r")
        cmd.append(file)

    with open(output_file, "w") as outfile:
        subprocess.run(cmd, stdout=outfile, stderr=outfile, check=True)


def _filter_builddeps(pip_download_output_file):
    """Find builddeps in output of pip download."""
    # Requirement is a sequence of non-whitespace, non-';' characters
    # Example: package, package==1.0, package[extra]==1.0
    requirement_re = r"[^\s;]+"
    # Leading whitespace => requirement is a build dependency
    # (because all recursive runtime dependencies were present in input files)
    builddep_re = re.compile(rf"^\s+Collecting ({requirement_re})")

    with open(pip_download_output_file) as f:
        matches = (builddep_re.match(line) for line in f)
        builddeps = set(match.group(1) for match in matches if match)

    return sorted(builddeps)


def find_builddeps(requirements_files, no_cache=False, ignore_errors=False):
    """
    Find build dependencies for packages in requirements files.

    :param requirements_files: list of requirements file paths
    :param no_cache: do not use pip cache when downloading packages
    :param ignore_errors: generate partial output even if pip download fails
    :return: list of build dependencies and bool whether output is partial
    """
    tmpdir = tempfile.mkdtemp(prefix=f"{SCRIPT_NAME}-")
    pip_output_file = Path(tmpdir) / "pip-download-output.txt"
    is_partial = False

    try:
        log.info("Running pip download, this may take a while")
        _pip_download(requirements_files, pip_output_file, tmpdir, no_cache)
    except subprocess.CalledProcessError:
        msg = f"Pip download failed, see {pip_output_file} for more info"
        if ignore_errors:
            log.error(msg)
            log.warning("Ignoring error...")
            is_partial = True
        else:
            raise FindBuilddepsError(msg)

    log.info("Looking for build dependencies in the output of pip download")
    builddeps = _filter_builddeps(pip_output_file)

    # Remove tmpdir only if pip download was successful
    if not is_partial:
        shutil.rmtree(tmpdir)

    return builddeps, is_partial


def generate_file_content(builddeps, is_partial):
    """
    Generate content to write to output file.

    :param builddeps: list of build dependencies to include in file
    :param is_partial: indicates that list of build dependencies may be partial
    :return: file content
    """
    # Month Day Year HH:MM:SS
    date = datetime.datetime.now().strftime("%b %d %Y %H:%M:%S")

    lines = [f"# Generated by {SCRIPT_NAME} on {date}"]
    if builddeps:
        lines.extend(builddeps)
    else:
        lines.append("# <no build dependencies found>")

    if is_partial:
        lines.append("# <pip download failed, output may be incomplete!>")

    file_content = "\n".join(lines)
    return file_content


def _parse_requirements_file(builddeps_file):
    """Find deps requirements-build.in file."""
    try:
        with open(builddeps_file) as f:
            # ignore line comments or comments added after dependency is declared
            requirement_re = re.compile(r"^([^\s#;]+)")
            matches = (requirement_re.match(line) for line in f)
            return set(match.group(1) for match in matches if match)
    except FileNotFoundError:
        # it's ok if the file doens't exist.
        return set()


def _sanity_check_args(ap, args):
    if args.only_write_on_update and not args.output_file:
        ap.error("--only-write-on-update requires an output-file (-o/--output-file).")


def main():
    """Run script."""
    ap = argparse.ArgumentParser(description=DESCRIPTION)
    ap.add_argument("requirements_files", metavar="REQUIREMENTS_FILE", nargs="+")
    ap.add_argument(
        "-o", "--output-file", metavar="FILE", help="write output to this file"
    )
    ap.add_argument(
        "-a",
        "--append",
        action="store_true",
        help="append to output file instead of overwriting",
    )
    ap.add_argument(
        "--no-cache",
        action="store_true",
        help="do not use pip cache when downloading packages",
    )
    ap.add_argument(
        "--ignore-errors",
        action="store_true",
        help="generate partial output even if pip download fails",
    )
    ap.add_argument(
        "--only-write-on-update",
        action="store_true",
        help=(
            "only write output file if dependencies will be modified - or new "
            "dependencies will be added if used in conjunction with -a/--append."
        ),
    )

    args = ap.parse_args()
    _sanity_check_args(ap, args)

    log.info(
        "Please make sure the input files meet the requirements of this script "
        "(see --help)"
    )

    builddeps, is_partial = find_builddeps(
        args.requirements_files,
        no_cache=args.no_cache,
        ignore_errors=args.ignore_errors,
    )

    if args.only_write_on_update:
        original_builddeps = _parse_requirements_file(args.output_file)
        if args.append:
            # append only new dependencies
            builddeps = sorted(set(builddeps) - original_builddeps)
        if not builddeps or set(builddeps) == original_builddeps:
            log.info("No new build dependencies found.")
            return

    file_content = generate_file_content(builddeps, is_partial)

    log.info("Make sure to pip-compile the output before submitting a Cachito request")
    if is_partial:
        log.warning("Pip download failed, output may be incomplete!")

    if args.output_file:
        mode = "a" if args.append else "w"
        with open(args.output_file, mode) as f:
            print(file_content, file=f)
    else:
        print(file_content)


if __name__ == "__main__":
    try:
        main()
    except FindBuilddepsError as e:
        log.error("%s", e)
        exit(1)
