# Tencent is pleased to support the open source community by making polaris-python available.
#
# Copyright (C) 2021 Tencent. All rights reserved.
#
# Licensed under the BSD 3-Clause License (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# https://opensource.org/licenses/BSD-3-Clause
#
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""Keep English README files paired with a linked Chinese translation."""

import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {".git", ".venv", ".pytest_cache", ".agents"}
CHINESE_LINK = "[\u4e2d\u6587](README-zh.md)"
ENGLISH_LINK = "[English](README.md)"


def readme_files():
    for path in REPO.rglob("README.md"):
        relative = path.relative_to(REPO)
        if EXCLUDED_PARTS.intersection(relative.parts):
            continue
        yield path


def prose(path):
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"!?\[[^\]]*\]\([^)]+\)", "", text)
    return text


def test_english_readmes_have_linked_chinese_translations():
    for path in readme_files():
        if re.search(r"[\u4e00-\u9fff]", prose(path)):
            continue
        chinese = path.with_name("README-zh.md")
        assert chinese.is_file(), f"{path.relative_to(REPO)} needs README-zh.md"
        assert CHINESE_LINK in path.read_text(encoding="utf-8")
        assert ENGLISH_LINK in chinese.read_text(encoding="utf-8")


def test_readme_language_links_do_not_dangle():
    for path in REPO.rglob("README*.md"):
        relative = path.relative_to(REPO)
        if EXCLUDED_PARTS.intersection(relative.parts):
            continue
        text = path.read_text(encoding="utf-8")
        if CHINESE_LINK in text:
            assert path.with_name("README-zh.md").is_file()
        if ENGLISH_LINK in text:
            assert path.with_name("README.md").is_file()
