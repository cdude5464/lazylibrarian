import logging
import os

from lazylibrarian import database
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import book_file, get_directory


def list_orphan_books():
    logger = logging.getLogger(__name__)
    startdir = get_directory('eBook')
    db = database.DBConnection()
    logger.debug(f"Counting directories: {startdir}")
    book_folders = []
    ignorefile = '.ll_ignore'
    for rootdir, dirnames, _filenames in os.walk(startdir):
        for directory in dirnames:
            # prevent magazine being scanned
            c = directory[0]
            dirname = os.path.join(rootdir, directory)
            if c in ["_", "."]:
                logger.debug(f'Skipping {dirname}')
            elif os.path.exists(os.path.join(rootdir, directory, ignorefile)):
                # ignore directories containing this special file
                logger.debug(f'Found .ll_ignore file in {dirname}')
            elif book_file(dirname, booktype='ebook', config=CONFIG, recurse=False):
                book_folders.append(dirname)
    logger.debug(f"Found {len(book_folders)} directories containing books")

    missing = []

    for folder in book_folders:
        book = os.path.splitext(os.path.basename(book_file(folder, booktype='ebook', config=CONFIG, recurse=False)))[0]
        match = db.match("select * from books where bookfile like ?", (f"%{book}%",))
        if not match and ' - ' in book:  # might be author - title
            book = book.split(' - ')[1]
            match = db.match("select * from books where bookfile like ?", (f"%{book}%",))
        if not match:
            missing.append(book)
    logger.info(f"Found: {len(book_folders) - len(missing)},  Not found: {len(missing)}")
    return missing


def list_orphan_audio():
    logger = logging.getLogger(__name__)
    startdir = get_directory('Audio')
    db = database.DBConnection()
    logger.debug(f"Counting directories: {startdir}")
    book_folders = []
    ignorefile = '.ll_ignore'
    for rootdir, dirnames, _filenames in os.walk(startdir):
        for directory in dirnames:
            # prevent magazine being scanned
            c = directory[0]
            dirname = os.path.join(rootdir, directory)
            if c in ["_", "."]:
                logger.debug(f'Skipping {dirname}')
            elif os.path.exists(os.path.join(rootdir, directory, ignorefile)):
                # ignore directories containing this special file
                logger.debug(f'Found .ll_ignore file in {dirname}')
            elif book_file(dirname, booktype='audio', config=CONFIG, recurse=False):
                book_folders.append(dirname)
    logger.debug(f"Found {len(book_folders)} directories containing audiobooks")

    missing = []

    for folder in book_folders:
        found = False
        for f in os.listdir(folder):
            basename = os.path.splitext(os.path.basename(f))[0]
            match = db.match("select * from books where audiofile like ?", (f"%{basename}%",))
            if match:
                found = True
                break
        if not found:
            missing.append(folder)
    logger.info(f"Found: {len(book_folders) - len(missing)},  Not found: {len(missing)}")
    return missing

def list_orphan_comics():
    logger = logging.getLogger(__name__)
    startdir = CONFIG['COMIC_DEST_FOLDER']
    if CONFIG.get_bool('COMIC_RELATIVE'):
        startdir = os.path.join(get_directory('eBook'), startdir)
    startdir = startdir.split('$')[0]
    db = database.DBConnection()
    logger.debug(f"Counting directories: {startdir}")
    comic_folders = []
    for rootdir, dirnames, _filenames in os.walk(startdir):
        for dirname in dirnames:
            dirname = os.path.join(rootdir, dirname)
            if book_file(dirname, booktype='comic', config=CONFIG, recurse=False):
                comic_folders.append(dirname)
    logger.debug(f"Found {len(comic_folders)} directories containing comics")

    missing = []
    found = 0
    for folder in comic_folders:
        for basename in os.listdir(folder):
            # try to match all issues in the folder
            if CONFIG.is_valid_booktype(basename, 'comic'):
                match = db.match("select * from comicissues where issuefile like ?", (f"%{basename}%",))
                if match:
                    found += 1
                else:
                    missing.append(basename)
    logger.info(f"Found: {found},  Not found: {len(missing)}")
    return missing

def list_orphan_magazines():
    logger = logging.getLogger(__name__)
    startdir = CONFIG['MAG_DEST_FOLDER']
    if CONFIG.get_bool('MAG_RELATIVE'):
        startdir = os.path.join(get_directory('eBook'), startdir)
    startdir = startdir.split('$')[0]
    db = database.DBConnection()
    logger.debug(f"Counting directories: {startdir}")
    mag_folders = []
    for rootdir, dirnames, _filenames in os.walk(startdir):
        for dirname in dirnames:
            dirname = os.path.join(rootdir, dirname)
            if book_file(dirname, booktype='magazine', config=CONFIG, recurse=False):
                mag_folders.append(dirname)
    logger.debug(f"Found {len(mag_folders)} directories containing magazines")

    missing = []
    found = 0
    for folder in mag_folders:
        for basename in os.listdir(folder):
            # try to match all issues in the folder
            if CONFIG.is_valid_booktype(basename, 'magazine'):
                match = db.match("select * from issues where issuefile like ?", (f"%{basename}%",))
                if match:
                    found += 1
                else:
                    missing.append(basename)
    logger.info(f"Found: {found},  Not found: {len(missing)}")
    return missing
