# test redis connection and basic operations on redis://default:redispw@localhost:32768
import redis
def test_redis_connection():
    r = redis.Redis(host='localhost', port=32768, password='redispw')
    # test connection
    assert r.ping() == True
    # test set and get
    r.set('test_key', 'test_value')
    assert r.get('test_key') == b'test_value'
    # test delete
    r.delete('test_key')
    assert r.get('test_key') == None

if __name__ == "__main__":
    test_redis_connection()
    print("All tests passed!")
    