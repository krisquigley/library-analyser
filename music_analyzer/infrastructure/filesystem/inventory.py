"""Read-only, bounded exact-byte inventory. Extensions are hints, not codec validation."""
import hashlib
import os
from pathlib import Path
import stat

from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.application.dto.catalogue import Inventory, ScanIssue, ScannedFile, ScanLimits


class LocalInventory:
    extensions = {'.flac', '.mp3', '.m4a', '.wav', '.ogg', '.opus', '.aiff', '.aif'}

    def _path(self, value):
        path = Path(os.path.abspath(value))
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('Symlink paths are not scanned; select a real directory/file')
        return path

    def _read(self, path, maximum):
        path = self._path(path)
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError('Not a regular file')
            if before.st_size > maximum:
                raise ValueError('File exceeds scan byte budget; increase explicit scan limits')
            digest = hashlib.sha256()
            count = 0
            while chunk := stream.read(min(1024 * 1024, maximum - count + 1)):
                count += len(chunk)
                if count > maximum:
                    raise ValueError('File grew beyond scan byte budget')
                digest.update(chunk)
            after = os.fstat(stream.fileno())
            current = path.stat(follow_symlinks=False)
            key = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            if key(before) != key(after) or key(after) != key(current) or count != after.st_size:
                raise ValueError('File changed while hashing; scan again')
            return ScannedFile(str(path), FileIdentity(digest.hexdigest(), count), after.st_mtime_ns, path.suffix.lower().lstrip('.'))

    def inventory(self, root, limits):
        root = self._path(root)
        if not root.is_dir():
            raise ValueError('Scan root must be an existing readable real directory')
        files, issues = [], []
        stack = [root]
        entries, total = 0, 0
        exhausted = False
        while stack and not exhausted:
            directory = stack.pop()
            try:
                self._path(directory)
                with os.scandir(directory) as children:
                    for entry in children:
                        entries += 1
                        if entries > limits.max_entries:
                            issues.append(ScanIssue(str(root), 'Entry limit reached; select a smaller root or increase --max-entries'))
                            exhausted = True
                            break
                        try:
                            if entry.is_symlink():
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(Path(entry.path))
                            elif Path(entry.name).suffix.lower() in self.extensions:
                                budget = min(limits.max_file_bytes, limits.max_total_bytes - total)
                                # Charge attempted bytes too: failed reads must not bypass the total budget.
                                size = entry.stat(follow_symlinks=False).st_size
                                if size > budget:
                                    raise ValueError('File exceeds remaining scan byte budget; increase limits or select smaller root')
                                # Reserve the entire permitted read on failure (e.g. a growing file).
                                total += budget
                                file = self._read(entry.path, budget)
                                total -= budget - file.identity.size
                                files.append(file)
                        except (OSError, ValueError) as error:
                            issues.append(ScanIssue(entry.path, str(error)))
            except (OSError, ValueError) as error:
                issues.append(ScanIssue(str(directory), str(error)))
        return Inventory(str(root), tuple(files), tuple(issues), not issues)

    def matches(self, location, track_id):
        try:
            return self._read(location, ScanLimits().max_file_bytes).identity.track_id == track_id
        except (OSError, ValueError):
            return False
