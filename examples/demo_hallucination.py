import beautifulsoup
import fake_library_that_does_not_exist


def calculate_analytics():
    # HalluGuard should flag this non-existent function call
    data = fetchUserData("http://example.com/api")
    
    # HalluGuard should flag this as a fake API
    fake_library_that_does_not_exist.do_something()

    return beautifulsoup.BeautifulSoup(data.text, 'html.parser')
