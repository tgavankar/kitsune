import random

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from gevent import Greenlet
import jingo
from redis import Redis

from sumo.utils import redis_client


@require_GET
def chat(request):
    """Display the current state of the chat queue."""
    nonce = None
    if request.user.is_authenticated():
        nonce = make_nonce()
        redis_client('chat').setex('chatnonce:{n}'.format(n=nonce), 
                                   request.user.username, 5 * 60)
    return jingo.render(request, 'chat/chat.html', {'nonce': nonce})


@never_cache
@require_GET
def queue_status(request):
    """Dump the queue status out of the cache.

    See chat.crons.get_queue_status.

    """
    xml = cache.get(settings.CHAT_CACHE_KEY)
    status = 200
    if not xml:
        xml = ''
        status = 503
    return HttpResponse(xml, mimetype='application/xml', status=status)


def make_nonce():
    return ''.join(random.choice('abcdefghijklmnopqrstuvwxyz234567')
                   for _ in xrange(10))

def set_sid_to_nick(nonce, sid):
    user_nick = redis_client('chat').get('chatnonce:{n}'.format(n=nonce))
    if user_nick is not None:
        redis_client('chat').set('chatsid:{n}'.format(n=sid), user_nick)

def get_nick_from_chatsid(sid):
    nick = redis_client('chat').get('chatsid:{n}'.format(n=sid))
    if nick is not None:
        return nick
    else:
        return sid

def chat_socketio(io):
    CHANNEL = 'world'

    def subscriber(io):
        try:
            redis_in = redis_client('chat')
            redis_in.subscribe(CHANNEL)
            redis_in_generator = redis_in.listen()

            # io.connected() never becomes false for some reason.
            while io.connected():
                for from_redis in redis_in_generator:
                    print 'Incoming: %s' % from_redis
                    if from_redis['type'] == 'message':  # There are also subscription notices.
                        io.send(from_redis['data'])
        finally:
            print "EXIT SUBSCRIBER %s" % io.session

    if io.on_connect():
        print "CONNECT %s" % io.session
    else:
        print "SOMETHING OTHER THAN CONNECT!"  # I have never seen this happen.

    # Hanging onto this might keep it from the GC:
    in_greenlet = Greenlet.spawn(subscriber, io)

    # Until the client disconnects, listen for input from the user:
    while io.connected():
        message = io.recv()
        if message:  # Always a list of 0 or 1 strings, I deduce from the source code
            to_redis = message[0]
            # On the chance that a user disconnects (loss of internet) and socketio
            # autoreconnects, a new session_id is given. However, the nonce is still
            # the same since the page hasn't been reloaded. There's a slim case where
            # getting the username via nonce fails (expired), so the username defaults
            # to the session ID, at the moment.
            # TODO: In the above case, XHR request a new nonce and update?
            # TODO: Replace flat strings with JSON objects (etc). 
            if to_redis[0:7] == 'Joined:': # Runs on reconnect
                set_sid_to_nick(to_redis[7:], io.session.session_id)
                redis_client('chat').publish(CHANNEL, get_nick_from_chatsid(io.session.session_id) + ' has joined')
            else:
                print 'Outgoing: %s' % to_redis
                redis_client('chat').publish(CHANNEL, get_nick_from_chatsid(io.session.session_id) + ': ' + to_redis)

    redis_client('chat').publish(CHANNEL, get_nick_from_chatsid(io.session.session_id) + ' has disconnected')
    print "EXIT %s" % io.session

    # Cleanup cache
    redis_client('chat').delete(io.session.session_id)

    # Each time I close the 2nd chat window, wait for the old socketio() view
    # to exit, and then reopen the chat page, the number of Incomings increases
    # by one. The subscribers are never exiting. This fixes that behavior:
    in_greenlet.kill()

    return HttpResponse()
