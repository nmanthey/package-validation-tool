# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Module to compare diffs directories from two package validation runs."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from package_validation_tool.package import JsonSerializableMixin
from package_validation_tool.utils import hash256sum

log = logging.getLogger(__name__)


@dataclass
class ArchiveDiffComparison:
    """Comparison result for a single archive's diffs."""

    files_only_in_a: List[str] = field(default_factory=list)
    files_only_in_b: List[str] = field(default_factory=list)
    files_with_different_content: List[str] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        """Return True if no differences found."""
        return not (
            self.files_only_in_a or self.files_only_in_b or self.files_with_different_content
        )


@dataclass
class DiffComparisonResult(JsonSerializableMixin):
    """Result of comparing two diffs directories."""

    identical: bool
    package_name: str
    archives_compared: List[str] = field(default_factory=list)
    differences: Dict[str, ArchiveDiffComparison] = field(default_factory=dict)

    def __post_init__(self):
        """Reconstruct nested dataclass objects from dicts after cache restoration."""
        for archive, diff in list(self.differences.items()):
            if isinstance(diff, dict):
                self.differences[archive] = ArchiveDiffComparison(**diff)


def _get_diff_files(directory: Path) -> Dict[str, str]:
    """
    Get all .arch and .repo files in directory, returning dict of relative path -> absolute path.

    Only returns the base path (without .arch/.repo suffix) as key.
    """
    files = {}
    for root, _, filenames in os.walk(directory):
        for filename in filenames:
            if filename.endswith((".arch", ".repo")):
                abs_path = os.path.join(root, filename)
                rel_path = os.path.relpath(abs_path, directory)
                # Remove .arch/.repo suffix for comparison key
                base_path = rel_path.rsplit(".", 1)[0]
                files[base_path] = abs_path
    return files


def compare_diffs_directories(
    dir_a: str,
    dir_b: str,
    package_name: Optional[str] = None,
    output_json_path: Optional[str] = None,
) -> bool:
    """
    Compare two diffs directories to check if package-to-upstream differences are identical.

    Args:
        dir_a: First diffs directory path
        dir_b: Second diffs directory path
        package_name: Optional package name to filter comparison
        output_json_path: Optional path to write JSON output

    Returns:
        True if diffs are identical, False otherwise
    """
    path_a = Path(dir_a)
    path_b = Path(dir_b)

    if not path_a.exists():
        log.error("Directory does not exist: %s", dir_a)
        return False
    if not path_b.exists():
        log.error("Directory does not exist: %s", dir_b)
        return False

    # If package_name specified, narrow to that subdirectory
    if package_name:
        path_a = path_a / package_name
        path_b = path_b / package_name

        if not path_a.exists():
            log.warning("Package directory does not exist in dir_a: %s", path_a)
        if not path_b.exists():
            log.warning("Package directory does not exist in dir_b: %s", path_b)

    # Get all diff files from both directories
    files_a = _get_diff_files(path_a) if path_a.exists() else {}
    files_b = _get_diff_files(path_b) if path_b.exists() else {}

    all_files = set(files_a.keys()) | set(files_b.keys())

    # Group files by archive
    archives: Dict[str, ArchiveDiffComparison] = {}

    for file_path in sorted(all_files):
        # Extract archive name from path (first component)
        parts = file_path.split(os.sep)
        archive_name = parts[0] if parts else "unknown"

        if archive_name not in archives:
            archives[archive_name] = ArchiveDiffComparison()

        in_a = file_path in files_a
        in_b = file_path in files_b

        if in_a and not in_b:
            archives[archive_name].files_only_in_a.append(file_path)
        elif in_b and not in_a:
            archives[archive_name].files_only_in_b.append(file_path)
        else:
            # Both exist, compare content via hash
            hash_a = hash256sum(files_a[file_path])
            hash_b = hash256sum(files_b[file_path])
            if hash_a != hash_b:
                archives[archive_name].files_with_different_content.append(file_path)

    identical = all(diff.identical for diff in archives.values())

    result = DiffComparisonResult(
        identical=identical,
        package_name=package_name or "",
        archives_compared=list(archives.keys()),
        differences=archives,
    )

    log.info(
        "Compared %d archives, identical: %s",
        len(archives),
        identical,
    )

    if output_json_path:
        result.write_json_output(output_json_path)

    return identical
