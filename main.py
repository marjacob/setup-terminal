#!/bin/env python3
import contextlib
import io
import json
import os
import re
import subprocess
import tempfile
import zipfile

import fire
import jinja2
import requests


def reflow_paragraphs(text: str) -> str:
    """
    Strip line feeds from paragraphs while preserving them between paragraphs.

    Source: https://stackoverflow.com/a/36242533
    """
    return re.sub(r"(?<!\n)\n(?![\n\t])", " ", text.replace("\r", ""))


def reflow_file(file: str, folder: str = "") -> str:
    with open(os.path.join(folder, file)) as f:
        return reflow_paragraphs(f.read())


@contextlib.contextmanager
def ClosedNamedTemporaryFile(data: str, mode: str = "w") -> str:
    """
    Temporary file that can be read by subprocesses on Windows.

    Source: https://stackoverflow.com/a/46501017
    """
    file = tempfile.NamedTemporaryFile(delete=False, mode=mode)
    try:
        with file:
            file.write(data)
        yield file.name
    finally:
        os.unlink(file.name)


class MSIXPackage(object):
    def __init__(self, name: str, zip: zipfile.ZipFile, preview: bool):
        if (match := MSIXPackage.match(name)) is None:
            raise ValueError("Not a CascadiaPackage filename.")

        self.cpu = match.group("CPU")
        self.name = name
        self.preview = preview
        self.version = match.group("Version")

        # Make sure that the target CPU is supported by Inno Setup.
        if self.cpu not in ["ARM64", "IA64", "x64", "x86"]:
            raise ValueError("Unsupported target CPU {}.", self.cpu)

        with zip.open(name) as pkg:
            self.archive = zipfile.ZipFile(io.BytesIO(pkg.read()))

    def __del__(self):
        try:
            self.archive.close()
        except AttributeError:
            pass

    @staticmethod
    def match(name: str):
        return re.fullmatch(
            r"""^
            (?P<Package>CascadiaPackage)
            (?:_)
            (?P<Version>\d+\.\d+\.\d+\.\d+)
            (?:_)
            (?P<CPU>.+)
            (?:\.)
            (?P<Extension>msix)
            $""", name, re.X)

    def extract(self, path):
        self.archive.extractall(path)


class MSIXBundle(object):
    def __init__(self, name: str, tag: str, zip: zipfile.ZipFile):
        if (match := MSIXBundle.match(name)) is None:
            raise ValueError("Not an AppBundle filename.")

        self.archive = zip
        self.name = name
        self.preview = match.group("Preview") is not None
        self.tag = tag
        self.version = match.group("Version")

    def __del__(self):
        self.archive.close()

    @staticmethod
    def match(name: str):
        # Examples:
        # Microsoft.WindowsTerminal_1.12.10393.0_8wekyb3d8bbwe.msixbundle
        # Microsoft.WindowsTerminal_Win10_1.12.10732.0_8wekyb3d8bbwe.msixbundle
        return re.fullmatch(
            r"""^
            (?P<Publisher>Microsoft)
            (?:\.)
            (?P<Package>WindowsTerminal)
            (?:_Win10)?
            (?P<Preview>Preview)?
            (?:_)
            (?P<Version>\d+\.\d+\.\d+\.\d+)
            (?:_)
            (?P<TemporaryKey>8wekyb3d8bbwe)
            (?:\.)
            (?P<Extension>msixbundle)
            $""", name, re.X)

    @classmethod
    def from_bundle(cls, name: str):
        if (match := cls.match(name)) is None:
            return None
        # Try guessing the most probable tag name.
        tag = "v" + match.group("Version")
        return cls(name, tag, zipfile.ZipFile(name))

    @classmethod
    def from_json(cls, doc: dict):
        tag: str = doc["tag_name"]

        for asset in doc["assets"]:
            name: str = asset["name"]

            if cls.match(name) is None:
                return None
            if asset["content_type"] != "application/octet-stream":
                return None

            file = requests.get(asset["browser_download_url"])

            if len(file.content) != asset["size"]:
                return None

            return cls(name, tag, zipfile.ZipFile(io.BytesIO(file.content)))

    @classmethod
    def from_json_file(cls, file: str):
        with open(file) as f:
            return cls.from_json(json.load(f))

    @classmethod
    def from_latest(cls, owner: str, repository: str):
        url = "https://{api}/repos/{owner}/{repository}/releases/{tag}".format(
            api="api.github.com",
            owner=owner,
            repository=repository,
            tag="latest")

        return cls.from_json(requests.get(url).json())

    def packages(self):
        for name in self.archive.namelist():
            try:
                pkg = MSIXPackage(name, self.archive, self.preview)
            except ValueError:
                continue
            yield pkg


def make_context(bundle: MSIXBundle) -> dict:
    return {
        "appid_preview": "337096F2-74EC-4B9C-B37A-0F8665B8F037",
        "appid_release": "F7BFA064-073D-4E1A-9038-874A2FD55525",
        "pitch": "Modern, fast, efficient, and powerful terminal application.",
        "product": "Windows Terminal",
        "program": "WindowsTerminal.exe",
        "publisher": "Microsoft Corporation",
        "publisher_url": "https://github.com/microsoft/terminal",
        "support_url": "https://github.com/microsoft/terminal/issues",
        "updates_url": "https://github.com/marjacob/setup-terminal/releases",
        "version": bundle.version,
    }


def make_setup(
    ctx: dict,
    dir: str,
    pkg: MSIXPackage,
    tpl: jinja2.Template,
) -> bool:
    """
    Generate an Inno Setup script and invoke the compiler.
    """
    setup = []
    for root, _, files in os.walk(dir):
        for file in files:
            src = os.path.join(root, file)
            dst = os.path.dirname(os.path.relpath(src, start=dir))
            setup.append((src, dst))

    # Match the file naming convention used by the microsoft/terminal project.
    name = "WindowsTerminal{preview}_{version}_{cpu}".format(
        cpu=pkg.cpu,
        preview="Preview" if pkg.preview else "",
        version=pkg.version,
    )

    cwd = os.path.abspath(os.curdir)
    out = os.path.join(cwd, "dist")

    ctx.update({
        "cpu": pkg.cpu,
        "files": setup,
        "name": name,
        "output_directory": out,
        "preview": pkg.preview,
    })

    # Render the template and invoke the compiler. This step is the only one
    # that requires Windows as the host operating system. Wine may be a viable
    # alternative for CI jobs.
    with ClosedNamedTemporaryFile(tpl.render(ctx)) as iss:
        try:
            subprocess.run(["ISCC.exe", iss])
        except subprocess.CalledProcessError:
            return False

    return True


def process_bundle(bundle: MSIXBundle):
    env = jinja2.Environment(auto_reload=False,
                             autoescape=jinja2.select_autoescape(),
                             cache_size=1,
                             loader=jinja2.FileSystemLoader("templates"),
                             lstrip_blocks=True,
                             trim_blocks=True)

    ctx = make_context(bundle)
    cwd = os.path.abspath(os.curdir)
    sub = os.path.join(cwd, "thirdparty", "terminal")
    tpl = env.get_template("setup.iss")

    # The original license text is formatted to fit within 80 columns of text
    # using a monospace font. This is fine for code, but the Inno Setup license
    # viewer is wider and can format the text using a proportional font.
    with ClosedNamedTemporaryFile(reflow_file("LICENSE", sub)) as license:
        ctx.update({"license": license})

        for pkg in bundle.packages():
            with tempfile.TemporaryDirectory() as tmp:
                pkg.extract(tmp)
                make_setup(ctx, tmp, pkg, tpl)


def main(bundle: str = "", version: str = ""):
    msix: MSIXBundle = None

    if bundle:
        msix = MSIXBundle.from_bundle(bundle)
    elif version:
        msix = MSIXBundle.from_json_file(version)
    else:
        msix = MSIXBundle.from_latest("microsoft", "terminal")

    process_bundle(msix)


if __name__ == "__main__":
    fire.Fire(main)
