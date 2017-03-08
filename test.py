import time
import sys

def foo():
    try:
        time.sleep(10)
    except (Exception, KeyboardInterrupt):
        print 'foo'
        raise

try:
    foo()
except KeyboardInterrupt:
    print 'bar'
    sys.exit(1)


