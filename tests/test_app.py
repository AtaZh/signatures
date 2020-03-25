#!/usr/bin/env python3
# coding: utf-8
# SPDX-License-Identifier: Apache-2.0


# Copyright 2020 AntiCompositeNumber

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#   http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import pytest  # type: ignore
import unittest.mock as mock
import sys
import os
import urllib.parse
from bs4 import BeautifulSoup  # type: ignore

sys.path.append(os.path.realpath(os.path.dirname(__file__) + "/../src"))
import app  # noqa: E402
from web import resources  # noqa: E402
import datatypes  # noqa: E402
import datasources  # noqa: E402

translated = pytest.mark.skipif(
    len(app.babel.list_translations()) < 2,
    reason="No non-English translations to test with",
)


@pytest.fixture(scope="module")
def flask_app():
    flask_app = app.create_app()[0]
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(flask_app):
    with flask_app.test_client() as client:
        yield client


def test_index(client):
    res = client.get("/")
    assert res.status_code == 200


def test_about(client):
    res = client.get("/about")
    assert res.status_code == 200


@translated
def test_uselang(client):

    en = client.get("/")
    en_soup = BeautifulSoup(en.data, "html.parser")
    en_lang = en_soup.find(id="currentLang").contents[0]
    assert en_lang == "English"

    fr = client.get("/?uselang=fr")
    fr_soup = BeautifulSoup(fr.data, "html.parser")
    fr_lang = fr_soup.find(id="currentLang").contents[0]
    assert fr_lang == "français"

    en2 = client.get("/")
    en_soup2 = BeautifulSoup(en2.data, "html.parser")
    en_lang2 = en_soup2.find(id="currentLang").contents[0]
    assert en_lang2 == "English"


@translated
def test_setlang(client):
    en = client.get("/")
    en_soup = BeautifulSoup(en.data, "html.parser")
    en_lang = en_soup.find(id="currentLang").contents[0]
    assert en_lang == "English"

    fr = client.get("/?setlang=fr", follow_redirects=True)
    fr_soup = BeautifulSoup(fr.data, "html.parser")
    fr_lang = fr_soup.find(id="currentLang").contents[0]
    assert fr_lang == "français"

    fr2 = client.get("/")
    fr_soup2 = BeautifulSoup(fr2.data, "html.parser")
    fr_lang2 = fr_soup2.find(id="currentLang").contents[0]
    assert fr_lang2 == "français"

    en2 = client.get("/?setlang=en", follow_redirects=True)
    en_soup2 = BeautifulSoup(en2.data, "html.parser")
    en_lang2 = en_soup2.find(id="currentLang").contents[0]
    assert en_lang2 == "English"


@mock.patch("datasources.get_sitematrix", return_value=[])
def test_check(get_sitematrix, client):
    req = client.get("/check")
    assert req.status_code == 200


def test_check_redirect(client):
    req = client.get(
        "/check?site=en.wikipedia.org&username=Example&sig=[[User:Example]]",
        follow_redirects=False,
    )
    assert 300 <= req.status_code < 400
    parsed = urllib.parse.urlparse(req.headers["Location"])
    assert parsed.path == "/check/en.wikipedia.org/Example"
    assert urllib.parse.parse_qs(parsed.query, strict_parsing=True) == {
        "sig": ["[[User:Example]]"]
    }


@pytest.mark.parametrize("badchar", ["#", "<", ">", "[", "]", "|", "{", "}", "/"])
def test_validate_username(badchar):
    with pytest.raises(ValueError):
        resources.validate_username(f"Example{badchar}User")


def test_validate_username_pass():
    resources.validate_username("Example")
    resources.validate_username("foo@bar.com")  # Grandfathered usernames have @


def test_get_default_sig():
    res = mock.Mock()
    res.return_value = "[[User:$1|$2]] ([[User talk:$1|talk]])"
    with mock.patch("datasources.backoff_retry", res):
        sig = resources.get_default_sig(
            "en.wikipedia.org", user="user", nickname="nick"
        )

    assert sig == "[[User:user|nick]] ([[User talk:user|talk]])"
    res.assert_called_once_with(
        "get",
        "https://en.wikipedia.org/w/index.php",
        output="text",
        params={"title": "MediaWiki:Signature", "action": "raw"},
    )


@pytest.mark.parametrize("userid,expected", [(((12345,),), True), ((), False)])
def test_check_user_exists(userid, expected):
    db_query = mock.Mock(return_value=userid)
    with mock.patch("datasources.db.do_db_query", db_query):
        exists = datasources.check_user_exists("enwiki", "Example")
        assert expected == exists
    db_query.assert_called_once_with("enwiki", mock.ANY, user="Example")


@pytest.mark.parametrize(
    "sig,failure", [("[[User:Example]]", False), ("[[User:Example2]]", None)]
)
def test_check_user_passed(sig, failure):
    data = resources.check_user("en.wikipedia.org", "Example", sig)
    assert data.signature == sig
    assert data.failure is failure
    assert data.username == "Example"
    assert data.site == "en.wikipedia.org"


@pytest.mark.parametrize(
    "props,failure,errors",
    [
        (
            datatypes.UserProps(nickname="[[User:Example]]", fancysig=True),
            False,
            datatypes.WebAppMessage.NO_ERRORS,
        ),
        (datatypes.UserProps(nickname="[[User:Example2]]", fancysig=True), None, ""),
        (
            datatypes.UserProps(nickname="Example2", fancysig=False),
            False,
            datatypes.WebAppMessage.SIG_NOT_FANCY,
        ),
    ],
)
def test_check_user_db(props, failure, errors):
    user_props = mock.Mock(return_value=props)
    with mock.patch("datasources.get_user_properties", user_props):
        data = resources.check_user("en.wikipedia.org", "Example")

    assert data.signature
    if errors:
        assert errors in data.errors
    assert data.failure is failure
    user_props.assert_called_once_with("Example", "enwiki")


@pytest.mark.parametrize(
    "exists,failure,errors",
    [
        (False, True, datatypes.WebAppMessage.USER_DOES_NOT_EXIST),
        (True, False, datatypes.WebAppMessage.DEFAULT_SIG),
    ],
)
def test_check_user_db_nosig(exists, failure, errors):
    user_props = mock.Mock(
        return_value=datatypes.UserProps(nickname="", fancysig=False)
    )
    user_exists = mock.Mock(return_value=exists)
    with mock.patch("datasources.get_user_properties", user_props):
        with mock.patch("datasources.check_user_exists", user_exists):
            data = resources.check_user("en.wikipedia.org", "Example")

    user_exists.assert_called_once_with("enwiki", "Example")
    user_props.assert_called_once_with("Example", "enwiki")
    assert data.failure is failure
    assert errors in data.errors


@pytest.mark.parametrize(
    "wikitext,html",
    [
        (
            "[[User:Example]]",
            '<p id="mwAQ"><a rel="mw:WikiLink" '
            'href="https://en.wikipedia.org/wiki/User:Example" '
            'title="User:Example" id="mwAg">User:Example</a></p>',
        )
    ],
)
def test_get_rendered_sig(wikitext, html):
    assert resources.get_rendered_sig("en.wikipedia.org", wikitext) == html


@pytest.mark.skip
def test_check_result():
    pass


def test_report(client):
    listdir = mock.Mock(return_value=["foo.example.org.json"])
    with mock.patch("os.listdir", listdir):
        res = client.get("/reports")

    assert res.status_code == 200
    assert b"foo.example.org" in res.data
