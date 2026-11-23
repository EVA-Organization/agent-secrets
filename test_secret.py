"""Pruebas de `secret` con un almacén en memoria. Correr: python3 -m unittest -v test_secret.py"""

import base64
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_loader = importlib.machinery.SourceFileLoader("secret_cli", str(HERE / "secret"))
_spec = importlib.util.spec_from_loader("secret_cli", _loader)
S = importlib.util.module_from_spec(_spec)
_loader.exec_module(S)

VALUE = "sk-test-0123456789abcdef"


class Memory:
    def __init__(self):
        self.data = {}

    def put(self, name, value):
        self.data[name] = value

    def get(self, name):
        return self.data.get(name)

    def delete(self, name):
        self.data.pop(name, None)

    def names(self):
        return list(self.data)


class Base(unittest.TestCase):
    def setUp(self):
        S._BACKEND = Memory()
        S._BACKEND.put("eva/demo/token", VALUE)
        self.tmp = Path(tempfile.mkdtemp())

    def call(self, *argv, stdin=""):
        """Corre `secret` en proceso; devuelve (código, stdout, stderr)."""
        out, err = io.TextIOWrapper(io.BytesIO()), io.TextIOWrapper(io.BytesIO())
        old = sys.stdin, sys.stdout, sys.stderr
        sys.stdin, sys.stdout, sys.stderr = io.StringIO(stdin), out, err
        try:
            code = S.main(list(argv))
        finally:
            sys.stdin, sys.stdout, sys.stderr = old
        out.flush(), err.flush()
        return code, out.buffer.getvalue().decode(), err.buffer.getvalue().decode()


class TestNames(Base):
    def test_valid(self):
        for name in ("eva/x", "eva/elevenlabs/api-key", "trabajo/jira/token.v2", "secret://eva/a/b"):
            S.check_name(name)

    def test_invalid(self):
        for name in ("eva", "EVA/x", "/eva/x", "eva//x", "eva/x/", "a/b/c/d/e", "eva/x y", "../x"):
            with self.assertRaises(S.Fail, msg=name):
                S.check_name(name)


class TestSetCheckLs(Base):
    def test_set_stdin_strips_one_newline(self):
        code, out, _ = self.call("set", "eva/new/key", "--stdin", stdin="abcdefgh1234\n")
        self.assertEqual(code, 0)
        self.assertEqual(S._BACKEND.get("eva/new/key"), "abcdefgh1234")
        self.assertNotIn("abcdefgh1234", out)

    def test_set_refuses_short_and_existing(self):
        self.assertEqual(self.call("set", "eva/new/key", "--stdin", stdin="short")[0], 1)
        code, _, err = self.call("set", "eva/demo/token", "--stdin", stdin="otro-valor-largo")
        self.assertEqual(code, 1)
        self.assertIn("--force", err)
        self.assertEqual(self.call("set", "eva/demo/token", "--stdin", "--force",
                                   stdin="otro-valor-largo")[0], 0)

    def test_check_never_prints_value(self):
        code, out, _ = self.call("check", "eva/demo/token")
        self.assertEqual(code, 0)
        self.assertNotIn(VALUE, out)
        self.assertIn(S.fingerprint("eva/demo/token", VALUE), out)
        self.assertEqual(self.call("check", "eva/nada/aqui")[0], 1)

    def test_fingerprint_depends_on_name_and_value(self):
        self.assertNotEqual(S.fingerprint("eva/a/b", VALUE), S.fingerprint("eva/a/c", VALUE))
        self.assertEqual(S.fingerprint("eva/a/b", VALUE), S.fingerprint("eva/a/b", VALUE))

    def test_ls_prefix(self):
        S._BACKEND.put("trabajo/jira/token", VALUE)
        self.assertEqual(self.call("ls")[1].split(), ["eva/demo/token", "trabajo/jira/token"])
        self.assertEqual(self.call("ls", "trabajo/")[1].split(), ["trabajo/jira/token"])

    def test_no_get_verb(self):
        with self.assertRaises(SystemExit):
            self.call("get", "eva/demo/token")

    def test_rm_needs_human(self):
        self.addCleanup(setattr, S, "confirm", S.confirm)
        S.confirm = lambda _q: False
        self.assertEqual(self.call("rm", "eva/demo/token")[0], 1)
        self.assertIsNotNone(S._BACKEND.get("eva/demo/token"))


class TestRedaction(Base):
    def test_all_encodings(self):
        redact = S.make_redactor({"eva/demo/token": VALUE})
        raw = VALUE.encode()
        for form in (VALUE, raw.hex(), base64.b64encode(raw).decode(),
                     base64.urlsafe_b64encode(raw).decode().rstrip("="),
                     '"' + VALUE + '"'):
            self.assertNotIn(VALUE, redact(form))
            self.assertIn("[secret://eva/demo/token]", redact(form))

    def test_multiline_lines(self):
        pem = "-----BEGIN KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQ\nZZZZ\n-----END KEY-----"
        redact = S.make_redactor({"eva/k/pem": pem})
        self.assertNotIn("MIIEvQIBADANBgkqhkiG9w0BAQ", redact("x MIIEvQIBADANBgkqhkiG9w0BAQ y"))


class TestRun(Base):
    def test_injects_and_redacts(self):
        code, out, _ = self.call("run", "-e", "T=eva/demo/token", "--", "sh", "-c",
                                 'echo "$T"; printf %s "$T" | base64; echo "$T" >&2; exit 3')
        self.assertEqual(code, 3)
        self.assertNotIn(VALUE, out)
        self.assertEqual(out.count("[secret://eva/demo/token]"), 2)

    def test_env_file(self):
        env = self.tmp / ".env.tpl"
        env.write_text("# comentario\nexport T=secret://eva/demo/token\nMODE='prod'\n")
        code, out, _ = self.call("run", "--env-file", str(env), "--", "sh", "-c",
                                 'echo "$MODE ${#T}"')
        self.assertEqual((code, out.strip()), (0, f"prod {len(VALUE)}"))

    def test_missing_secret_and_no_refs(self):
        code, _, err = self.call("run", "-e", "T=eva/no/existe", "--", "true")
        self.assertEqual(code, 1)
        self.assertIn("secret set eva/no/existe", err)
        self.assertEqual(self.call("run", "--", "true")[0], 1)


class TestRender(Base):
    def test_writes_0600(self):
        tpl = self.tmp / "conf.tpl"
        tpl.write_text("token={{secret:eva/demo/token}}\n")
        out = self.tmp / "conf.env"
        code, stdout, _ = self.call("render", str(tpl), str(out))
        self.assertEqual(code, 0)
        self.assertEqual(out.read_text(), f"token={VALUE}\n")
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)
        self.assertNotIn(VALUE, stdout)

    def test_refuses_symlink_and_sensitive_destinations(self):
        tpl = self.tmp / "conf.tpl"
        tpl.write_text("{{secret:eva/demo/token}}")
        link = self.tmp / "link"
        os.symlink(self.tmp / "real", link)
        for dest in (link, self.tmp / ".bashrc", self.tmp / ".git" / "hooks" / "pre-commit",
                     self.tmp / ".ssh" / "config", self.tmp / ".claude" / "settings.json",
                     self.tmp / ".config" / "autostart" / "x.desktop"):
            self.assertEqual(self.call("render", str(tpl), str(dest))[0], 1, msg=str(dest))
        self.assertFalse((self.tmp / "real").exists())

    def test_needs_placeholder(self):
        tpl = self.tmp / "plain.tpl"
        tpl.write_text("nada")
        self.assertEqual(self.call("render", str(tpl), str(self.tmp / "o"))[0], 1)


if __name__ == "__main__":
    with contextlib.suppress(SystemExit):
        unittest.main()
