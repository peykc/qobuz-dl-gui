import os
import sys

from setuptools import find_packages, setup

# Single source of truth for version (also used by in-app updater)
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)
from qobuz_dl.version import __version__ as pkg_version

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
    python_requires=">=3.6",
)

# rm -f dist/*
# python3 setup.py sdist bdist_wheel
# twine upload dist/*
