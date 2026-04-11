from setuptools import setup, find_packages

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
]

setup(
    name=pkg_name,
    version="0.9.9.11",
    author="Vitiko",
    author_email="vhnz98@gmail.com",
    description="The modern Lossless and Hi-Res music downloader for Qobuz with a beautiful Web UI",
    long_description=read_file("README.md"),
    long_description_content_type="text/markdown",
    url="https://github.com/vitiko98/Qobuz-DL",
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
