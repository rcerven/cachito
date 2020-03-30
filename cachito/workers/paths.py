# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import pathlib

from cachito import paths
from cachito.workers.config import get_worker_config

log = logging.getLogger(__name__)


class RequestBundleDir(paths.RequestBundleDir):
    """
    Represents a concrete request bundle directory used on worker whose root
    directory defaults to ``cachito_bundles_dir`` in config.

    By default, this request bundle directory and its dependency directory will
    be created when this object is instantiated.

    :param int request_id: the request ID.
    """

    def __new__(cls, request_id):
        root_dir = get_worker_config().cachito_bundles_dir
        self = super().__new__(cls, request_id, root_dir)

        log.debug("Ensure directory %s exists.", self)
        log.debug("Ensure directory %s exists.", self.deps_dir)
        self.deps_dir.mkdir(parents=True, exist_ok=True)

        return self


# Similar with cachito.paths.RequestBundleDir, this base type will be the
# correct type for Linux or Windows individually.
class SourcesDir(type(pathlib.Path())):
    """
    Represents a sources directory tree for a package, which will be created
    automatically when this object is instantiated.

    :param str repo_name: a namespaced repository name of package. For example,
        ``release-engineering/retrodep``.
    :param str ref: the revision reference used to construct archive filename.
    """

    def __new__(cls, repo_name, ref):
        self = super().__new__(cls, get_worker_config().cachito_sources_dir)

        repo_relative_dir = pathlib.Path(*repo_name.split("/"))
        self.package_dir = self.joinpath(repo_relative_dir)
        self.archive_path = self.joinpath(repo_relative_dir, f"{ref}.tar.gz")

        log.debug("Ensure directory %s exists.", self.package_dir)
        self.package_dir.mkdir(parents=True, exist_ok=True)

        return self
