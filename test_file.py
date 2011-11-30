import os, random, sys

size = int(sys.argv[1]) #arg 1 - random string size

def randomString(size):
    return os.urandom(size)

def writeAndRead(size, filename):
    f = open(filename, 'w')
    random_string = randomString(size)
    f.write(random_string)
    f.close()
    f = open(filename, 'r+')
    cmp_str = f.read()
    f.close()
    assert random_string == cmp_str

def testMultipleSizes():
    for i in range(101):
        writeAndRead(i*size, 'mountpoint/test_file.txt')

testMultipleSizes()
