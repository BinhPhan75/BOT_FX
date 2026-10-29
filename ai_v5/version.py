"""
=========================================================
XuTho AI V5
Version Information
=========================================================
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class VersionInfo:
    NAME: str = "XuTho AI"
    VERSION: str = "5.0.0"
    BUILD: str = "2026.07.17"
    AUTHOR: str = "Binh Phan & ChatGPT"
    CODENAME: str = "Shadow Learning"
    STATUS: str = "Development"

    @property
    def full_version(self) -> str:
        return f"{self.NAME} v{self.VERSION}"

    @property
    def banner(self) -> str:
        return (
            "\n"
            "=====================================================\n"
            f" {self.NAME}\n"
            f" Version : {self.VERSION}\n"
            f" Build   : {self.BUILD}\n"
            f" Author  : {self.AUTHOR}\n"
            f" Status  : {self.STATUS}\n"
            "=====================================================\n"
        )


VERSION = VersionInfo()


def print_banner() -> None:
    print(VERSION.banner)
    print(f"Startup Time : {datetime.now():%Y-%m-%d %H:%M:%S}")
    print()