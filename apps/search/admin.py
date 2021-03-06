from datetime import datetime

from django.conf import settings
from django.contrib import admin
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect, Http404
from django.shortcuts import render_to_response
from django.template import RequestContext

from waffle.models import Flag

from search import es_utils
from search.es_utils import (get_doctype_stats, get_indexes, delete_index,
                             ESTimeoutError, ESMaxRetryError,
                             ESIndexMissingException)
from search.models import Record, get_search_models
from search.tasks import ES_REINDEX_PROGRESS, reindex_with_progress
from sumo.urlresolvers import reverse


class DeleteError(Exception):
    pass


def handle_delete(request):
    index_to_delete = request.POST['delete_index']

    # Rule 1: Has to start with the ES_INDEX_PREFIX.
    if not index_to_delete.startswith(settings.ES_INDEX_PREFIX):
        raise DeleteError('"%s" is not a valid index name.' % index_to_delete)

    # Rule 2: Must be an existing index.
    indexes = [name for name, count in get_indexes()]
    if index_to_delete not in indexes:
        raise DeleteError('"%s" does not exist.' % index_to_delete)

    # Rule 3: Don't delete the READ index.
    if index_to_delete == es_utils.READ_INDEX:
        raise DeleteError('"%s" is the read index.' % index_to_delete)

    delete_index(index_to_delete)

    return HttpResponseRedirect(request.path)


def search(request):
    """Render the admin view containing search tools.

    It's a dirty little secret that you can fire off 2 concurrent
    reindexing jobs; the disabling of the buttons while one is running
    is advisory only.  This lets us recover if celery crashes and
    doesn't clear the memcached token.

    """
    if not request.user.has_perm('search.reindex'):
        raise PermissionDenied

    delete_error_message = ''
    es_error_message = ''
    stats = {}

    reindex_requested = 'reindex' in request.POST
    if reindex_requested:
        reindex_with_progress.delay(es_utils.WRITE_INDEX)

    delete_requested = 'delete_index' in request.POST
    if delete_requested:
        try:
            return handle_delete(request)
        except DeleteError, e:
            delete_error_message = e.msg
        except ESMaxRetryError:
            delete_error_message = ('Elastic Search is not set up on this '
                                    'machine or is not responding. '
                                    '(MaxRetryError)')
        except ESIndexMissingException:
            delete_error_message = ('Index is missing. Press the reindex '
                                    'button below. (IndexMissingException)')
        except ESTimeoutError:
            delete_error_message = ('Connection to Elastic Search timed out. '
                                    '(TimeoutError)')

    stats = None
    write_stats = None
    indexes = []
    try:
        # This gets index stats, but also tells us whether ES is in
        # a bad state.
        try:
            stats = get_doctype_stats(es_utils.READ_INDEX)
        except ESIndexMissingException:
            stats = None
        try:
            write_stats = get_doctype_stats(es_utils.WRITE_INDEX)
        except ESIndexMissingException:
            write_stats = None
        indexes = get_indexes()
        indexes.sort(key=lambda m: m[0])
    except ESMaxRetryError:
        es_error_message = ('Elastic Search is not set up on this machine '
                            'or is not responding. (MaxRetryError)')
    except ESIndexMissingException:
        es_error_message = ('Index is missing. Press the reindex button '
                            'below. (IndexMissingException)')
    except ESTimeoutError:
        es_error_message = ('Connection to Elastic Search timed out. '
                            '(TimeoutError)')

    recent_records = reversed(Record.uncached.order_by('starttime')[:20])

    es_waffle_flag = Flag.objects.get(name=u'elasticsearch')

    return render_to_response(
        'search/admin/search.html',
        {'title': 'Search',
         'es_waffle_flag': es_waffle_flag,
         'doctype_stats': stats,
         'doctype_write_stats': write_stats,
         'indexes': indexes,
         'read_index': es_utils.READ_INDEX,
         'write_index': es_utils.WRITE_INDEX,
         'delete_error_message': delete_error_message,
         'es_error_message': es_error_message,
         'recent_records': recent_records,
          # Dim the buttons even if the form loads before the task fires:
         'progress': cache.get(ES_REINDEX_PROGRESS,
                               '0.001' if reindex_requested else ''),
         'progress_url': reverse('search.reindex_progress'),
         'interval': settings.ES_REINDEX_PROGRESS_BAR_INTERVAL * 1000},
        RequestContext(request, {}))


admin.site.register_view('search', search, 'Search - Index Maintenance')


def _fix_value_dicts(values_dict_list):
    """Takes a values dict returned from an S and humanizes it"""
    for dict_ in values_dict_list:
        # Convert datestamps (which are in seconds since epoch) to
        # Python datetime objects.
        for key in ('indexed_on', 'created', 'updated'):
            if key in dict_:
                dict_[key] = datetime.fromtimestamp(int(dict_[key]))
    return values_dict_list


def index_view(request):
    requested_bucket = request.GET.get('bucket', '')
    requested_id = request.GET.get('id', '')
    last_20_by_bucket = None
    data = None

    bucket_to_model = dict(
        [(cls._meta.db_table, cls) for cls in get_search_models()])

    if requested_bucket and requested_id:
        # The user wants to see a specific item in the index, so we
        # attempt to fetch it from the index and show that
        # specifically.
        if requested_bucket not in bucket_to_model:
            raise Http404

        cls = bucket_to_model[requested_bucket]
        data = list(cls.search().filter(id=requested_id).values_dict())
        if not data:
            raise Http404
        data = _fix_value_dicts(data)[0]

    else:
        # Create a list of (class, list-of-dicts) showing us the most
        # recently indexed items for each bucket. We only display the
        # id, title and indexed_on fields, so only pull those back from
        # ES.
        last_20_by_bucket = [
            (cls_name,
             _fix_value_dicts(cls.search()
                                 .values_dict()
                                 .order_by('-indexed_on')[:20]))
            for cls_name, cls in bucket_to_model.items()]

    return render_to_response(
        'search/admin/index.html',
        {'title': 'Index Browsing',
         'buckets': [cls_name for cls_name, cls in bucket_to_model.items()],
         'last_20_by_bucket': last_20_by_bucket,
         'requested_bucket': requested_bucket,
         'requested_id': requested_id,
         'requested_data': data
         },
        RequestContext(request, {}))


admin.site.register_view('index', index_view, 'Search - Index Browsing')
