#!/usr/bin/env python3
"""Small stdlib-only checks for the one-command source installer."""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import install  # noqa: E402
import uninstall  # noqa: E402


def main():
    with tempfile.TemporaryDirectory(prefix="tectdist-install-") as home:
        assert install.default_rc({"HOME": home, "SHELL": "/bin/zsh"}) \
            == os.path.join(home, ".zshrc")
        assert install.default_rc({"HOME": home, "SHELL": "/bin/bash"},
                                  platform="linux") \
            == os.path.join(home, ".bashrc")
        assert install.default_rc({"HOME": home, "SHELL": "/bin/bash"},
                                  platform="darwin") \
            == os.path.join(home, ".bash_profile")
        fish_rc = install.default_rc({"HOME": home, "SHELL": "/usr/bin/fish"})
        assert fish_rc == os.path.join(home, ".config", "fish", "config.fish")
        assert install.default_rc({"HOME": home, "SHELL": "/bin/ksh"}) \
            == os.path.join(home, ".profile")

        zsh_rc = os.path.join(home, "nested", ".zshrc")
        assert install.add_path_entry(zsh_rc) is True
        assert install.add_path_entry(zsh_rc) is False
        with open(zsh_rc, encoding="utf-8") as f:
            zsh_text = f.read()
        assert zsh_text.count(install.MARKER) == 1
        assert "export PATH='" in zsh_text

        assert install.add_path_entry(fish_rc) is True
        with open(fish_rc, encoding="utf-8") as f:
            fish_text = f.read()
        assert "fish_add_path '" in fish_text

        assert install.path_line(zsh_rc, "/tmp/native bin") == \
            "export PATH='/tmp/native bin':\"$PATH\""

        assert uninstall.clean_rc(zsh_rc) is True
        assert uninstall.clean_rc(fish_rc) is True
        with open(zsh_rc, encoding="utf-8") as f:
            assert install.MARKER not in f.read()
        with open(fish_rc, encoding="utf-8") as f:
            assert install.MARKER not in f.read()

        hostile = "/tmp/a'$(touch nope)"
        assert install.shell_quote(hostile) == "'/tmp/a'\"'\"'$(touch nope)'"

    print("check_install: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
