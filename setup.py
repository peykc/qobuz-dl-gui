import os
import re

from setuptools import find_packages, setup

# Single source of truth for version (also used by in-app updater)
_root = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_root, "qobuz_dl", "version.py"), "r", encoding="utf-8") as f:
    _version_text = f.read()
_version_match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', _version_text, re.M)
if not _version_match:
    raise RuntimeError("Could not find __version__ in qobuz_dl/version.py")
pkg_version = _version_match.group(1)

pkg_name = "qobuz-dl"


def read_file(fname):
    with open(fname, "r") as f:
        return f.read()


requirements = [
    "pathvalidate",
    "requests",
    "mutagen",
    "tqdm",
    "pick==1.6.0",
    "beautifulsoup4",
    "colorama",
    "flask",
    "pywebview>=5.0",
    "pyperclip>=1.8.2",
    "packaging>=21.0",
]

setup(
    name=pkg_name,
    version=pkg_version,
    author="Vitiko",
    author_email="vhnz98@gmail.com",
    description="The modern Lossless and Hi-Res music downloader for Qobuz with a beautiful Web UI",
    long_description=read_file("README.md"),
    long_description_content_type="text/markdown",
    url="https://github.com/peykc/qobuz-dl-gui",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "qobuz-dl = qobuz_dl:main",
            "qdl = qobuz_dl:main",
            "qobuz-dl-gui = qobuz_dl.gui_app:main",
        ],
    },
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "qobuz_dl": ["gui/*", "gui/**/*"],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License (GPL)",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
)

# rm -f dist/*
# python3 setup.py sdist bdist_wheel
# twine upload dist/*
