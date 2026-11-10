"""Reproduce Hermes Python extraction using two actual archive entries.

Use an isolated scratch parent. This reads the archive and extracts only the
case-colliding terminfo symlink/file, never the Python binary or executable code.
Exit 1 is the installer symptom; exit 0 means these entries extract successfully.
"""
import argparse
import errno
from pathlib import Path
import tarfile
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--scratch-parent', type=Path, required=True)
    args = parser.parse_args()
    with tarfile.open(args.archive) as archive, tempfile.TemporaryDirectory(
        prefix='hermes-case-repro-', dir=args.scratch_parent
    ) as scratch:
        # Preserve original archive order: uppercase alias precedes lowercase data.
        names = ['python/share/terminfo/N/NCR260VT300WPP',
                 'python/share/terminfo/n/ncr260vt300wpp']
        members = [archive.getmember(name) for name in names]
        assert members[0].issym() and members[1].isfile()
        assert members[0].linkname == '../n/ncr260vt300wpp'
        try:
            for member in members:
                # Two pinned known-safe paths; default 3.14 filtering otherwise
                # raises a filter error instead of the installer's ELOOP symptom.
                archive.extract(member, scratch, filter='fully_trusted')
        except OSError as exc:
            if exc.errno != errno.ELOOP:
                raise
            print('REPRODUCED: ELOOP extracting case-colliding Python terminfo entries')
            return 1
        print('PASS: Python terminfo entries extracted separately')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
