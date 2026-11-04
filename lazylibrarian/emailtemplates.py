#  This file is part of Lazylibrarian.
#  Lazylibrarian is free software':'you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#  Lazylibrarian is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  You should have received a copy of the GNU General Public License
#  along with Lazylibrarian.  If not, see <http://www.gnu.org/licenses/>.

#  Purpose:
#    The emails sent to users: login details for new accounts, and files for subscribers.
#    Each is written in the recipient's language. A template is looked for in the data dir as
#    logintemplate.<lang>.text (eg logintemplate.sk.text), then logintemplate.text, and the
#    translated built-in message is used when neither exists. Same for filetemplate.

import logging
import os

import lazylibrarian
from lazylibrarian import database, i18n
from lazylibrarian.filesystem import DIRS, path_isfile, syspath

LOGIN = 'logintemplate'
FILE = 'filetemplate'
_FIELDS = {LOGIN: ('{username}', '{password}', '{permission}'),
           FILE: ('{name}', '{method}', '{link}')}

# what happened to the file, the {method} of a file template
ATTACHED = i18n.N_('is attached')
AVAILABLE = i18n.N_('is available for download')
NOT_AVAILABLE = i18n.N_('is not available')
NOT_IN_FORMAT = i18n.N_('is available for download, but not as %(format)s')


def user_language(userid):
    """ The language to write to a user in: their interface language, else the notification language """
    if userid:
        db = database.DBConnection()
        try:
            res = db.match('SELECT UI_Lang from users where UserID=?', (userid,))
        finally:
            db.close()
        lang = (res['UI_Lang'] or '').strip() if res else ''
        if lang and lang in i18n.available_languages():
            return lang
    return i18n.notify_language()


def _builtin(kind):
    if kind == LOGIN:
        return i18n.gettext("Your lazylibrarian username is {username}\nYour password is {password}\n"
                            "You can log in to lazylibrarian and change these to something more memorable\n"
                            "You have been given {permission} access\n")
    return "{name}{method}{link}"


def _missing(text, kind):
    return [item for item in _FIELDS[kind] if item not in text]


def load_template(kind, lang):
    """ The template for kind in lang, call inside i18n.language(lang) """
    logger = logging.getLogger(__name__)
    for fname in (f'{kind}.{lang}.text', f'{kind}.text'):
        msg_file = os.path.join(DIRS.DATADIR, fname)
        if not path_isfile(msg_file):
            continue
        try:
            with open(syspath(msg_file), encoding='utf-8') as msg_data:
                res = msg_data.read()
        except Exception as e:
            logger.error(f'Failed to load {msg_file}, {type(e).__name__} {str(e)}')
            break
        missing = _missing(res, kind)
        if missing:
            logger.warning(f"Invalid template in {msg_file}, no {missing[0]}")
            break
        logger.debug(f"Using template {msg_file}")
        return res
    res = _builtin(kind)
    if _missing(res, kind):
        logger.warning(f"Translated {kind} for {lang} has lost a field, using English")
        with i18n.language(i18n.DEFAULT_LANGUAGE):
            res = _builtin(kind)
    return res


def permission_name(perms):
    """ The name of a set of permissions, in the current language """
    if perms == lazylibrarian.perm_admin:
        return i18n.gettext('Admin')
    if perms == lazylibrarian.perm_friend:
        return i18n.gettext('Friend')
    if perms == lazylibrarian.perm_guest:
        return i18n.gettext('Guest')
    return i18n.gettext('Custom %(perms)s') % {'perms': perms}


def login_message(username, password, perms, lang=None):
    """ Subject and text of the email with a new user's login details """
    lang = lang or i18n.notify_language()
    with i18n.language(lang):
        msg = load_template(LOGIN, lang).replace('{username}', username).replace(
            '{password}', password).replace('{permission}', permission_name(perms))
        return i18n.gettext('LazyLibrarian New Account'), msg


def file_message(name, method, link='', lang=None, **kwargs):
    """ Subject and text of the email about a file, method is one of ATTACHED, AVAILABLE,
        NOT_AVAILABLE or NOT_IN_FORMAT (with format=) """
    lang = lang or i18n.notify_language()
    with i18n.language(lang):
        method = f" {i18n.gettext(method) % kwargs if kwargs else i18n.gettext(method)}"
        if link:
            method += ' '
        msg = load_template(FILE, lang).replace('{name}', name).replace(
            '{method}', method).replace('{link}', link or '')
        return i18n.gettext('Message from LazyLibrarian'), msg
