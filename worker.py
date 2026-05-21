import redis
from rq import SimpleWorker, Queue 

listen = ['default']

conn = redis.Redis(host='127.0.0.1', port=6379)


if __name__ == '__main__':

    queues = [Queue(name, connection=conn) for name in listen]

    worker = SimpleWorker(queues, connection=conn)
    
    print("--- Worker is running. Waiting for jobs... ---")
    worker.work()