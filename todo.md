# Data source
    Western novel:  https://www.goodreads.com/  
                    https://www.isfdb.org/
                    https://openlibrary.org/
                    Wikidata
    Lightnovel:     https://ranobedb.org/
                    https://www.novelupdates.com/
                    Erank
                    BookWalker Japan

# GOODREADS
    Title
    Desc
    Genre
    Review
    Point

# Plan
    https://www.goodreads.com/list: https://www.goodreads.com/list/show/1 -> increase and get all books
    other plan: get isbn from open library -> https://www.goodreads.com/search?q={isbn}: Ex: https://www.goodreads.com/search?q=9781635574043
        if have same title -> remove
# DATA
    https://www.kaggle.com/datasets/pypiahmad/goodreads-book-reviews1
    https://www.kaggle.com/datasets/pooriamst/best-books-ever-dataset
    https://www.kaggle.com/datasets/middlelight/goodreadsbookswithgenres
    https://openlibrary.org/developers/dumps
    https://www.goodreads.com
    https://cseweb.ucsd.edu/~jmcauley/datasets/goodreads.
    https://developers.google.com/books?hl=vi
    https://www.goodreads.com/shelf/show/fiction?page=1
    https://docs.hardcover.app/api/getting-started/
    https://hardcover.app
    https://thestorygraph.com/
    https://www.librarything.com/

# auto_get
    playwright -> sign in using gmail -> make profile name ./goodreads
    get https://www.goodreads.com/new_releases/2017/1 (until 2026/06)-> get all book url -> use requests to get data of its urrl -> if the book already in .db -> pass -> if not -> get data of each book to satisfy the goodreads_books.db(can remove popular shelf) also base on goodreads_1data (should wait to the books appear quite a long time -> wait until appear)

# Goodreads
    search: https://www.goodreads.com/search?q=House+of+Earth+and+Blood&ref=nav_sb_noss_l_24
    shelf: https://www.goodreads.com/shelf/show/fiction?page=1

# Todo
    Get and Merge data of all books from 3 source: hardcover, goodreads, openlibrary, the column should be devided clearly into 3 source: hardcover, goodreads, openlibrary