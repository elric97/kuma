# -*- coding: utf-8 -*-
from django.http import Http404
from django.shortcuts import get_object_or_404, get_list_or_404, render
from django.views.decorators.http import require_GET

from kuma.core.decorators import block_user_agents
from kuma.core.utils import paginate

from ..constants import DOCUMENTS_PER_PAGE
from ..decorators import process_document_path, prevent_indexing
from ..models import Document, DocumentTag, ReviewTag, LocalizationTag


@block_user_agents
@require_GET
def documents(request, tag=None):
    """
    List wiki documents depending on the optionally given tag.
    """
    # Taggit offers a slug - but use name here, because the slugification
    # stinks and is hard to customize.
    tag_obj = None
    if tag:
        matching_tags = get_list_or_404(DocumentTag, name__iexact=tag)
        for matching_tag in matching_tags:
            if matching_tag.name.lower() == tag.lower():
                tag_obj = matching_tag
                break
    docs = Document.objects.filter_for_list(locale=request.LANGUAGE_CODE,
                                            tag=tag_obj)
    paginated_docs = paginate(request, docs, per_page=DOCUMENTS_PER_PAGE)
    context = {
        'documents': paginated_docs,
        'count': docs.count(),
        'tag': tag,
    }
    return render(request, 'wiki/list/documents.html', context)


@block_user_agents
@require_GET
def tags(request):
    """
    Returns listing of all tags
    """
    tags = DocumentTag.objects.order_by('name')
    tags = paginate(request, tags, per_page=DOCUMENTS_PER_PAGE)
    return render(request, 'wiki/list/tags.html', {'tags': tags})


@block_user_agents
@require_GET
def needs_review(request, tag=None):
    """
    Lists wiki documents with revisions flagged for review
    """
    tag_obj = tag and get_object_or_404(ReviewTag, name=tag) or None
    docs = Document.objects.filter_for_review(locale=request.LANGUAGE_CODE,
                                              tag=tag_obj)
    paginated_docs = paginate(request, docs, per_page=DOCUMENTS_PER_PAGE)
    context = {
        'documents': paginated_docs,
        'count': docs.count(),
        'tag': tag_obj,
        'tag_name': tag,
    }
    return render(request, 'wiki/list/needs_review.html', context)


@block_user_agents
@require_GET
def with_localization_tag(request, tag=None):
    """
    Lists wiki documents with localization tag
    """
    tag_obj = tag and get_object_or_404(LocalizationTag, name=tag) or None
    docs = Document.objects.filter_with_localization_tag(
        locale=request.LANGUAGE_CODE, tag=tag_obj)
    paginated_docs = paginate(request, docs, per_page=DOCUMENTS_PER_PAGE)
    context = {
        'documents': paginated_docs,
        'count': docs.count(),
        'tag': tag_obj,
        'tag_name': tag,
    }
    return render(request, 'wiki/list/with_localization_tags.html', context)


@block_user_agents
@require_GET
def with_errors(request):
    """
    Lists wiki documents with (KumaScript) errors
    """
    docs = Document.objects.filter_for_list(locale=request.LANGUAGE_CODE,
                                            errors=True)
    paginated_docs = paginate(request, docs, per_page=DOCUMENTS_PER_PAGE)
    context = {
        'documents': paginated_docs,
        'count': docs.count(),
        'errors': True,
    }
    return render(request, 'wiki/list/documents.html', context)


@block_user_agents
@require_GET
def without_parent(request):
    """Lists wiki documents without parent (no English source document)"""
    docs = Document.objects.filter_for_list(locale=request.LANGUAGE_CODE,
                                            noparent=True)
    paginated_docs = paginate(request, docs, per_page=DOCUMENTS_PER_PAGE)
    context = {
        'documents': paginated_docs,
        'count': docs.count(),
        'noparent': True,
    }
    return render(request, 'wiki/list/documents.html', context)


@block_user_agents
@require_GET
def top_level(request):
    """Lists documents directly under /docs/"""
    docs = Document.objects.filter_for_list(locale=request.LANGUAGE_CODE,
                                            toplevel=True)
    paginated_docs = paginate(request, docs, per_page=DOCUMENTS_PER_PAGE)
    context = {
        'documents': paginated_docs,
        'count': docs.count(),
        'toplevel': True,
    }
    return render(request, 'wiki/list/documents.html', context)


@block_user_agents
@require_GET
@process_document_path
@prevent_indexing
def revisions(request, document_slug, document_locale):
    """
    List all the revisions of a given document.
    """
    locale = request.GET.get('locale', document_locale)
    document = get_object_or_404(Document.objects
                                         .select_related('current_revision'),
                                 locale=locale,
                                 slug=document_slug)
    if document.current_revision is None:
        raise Http404

    def get_previous(revisions):
        for current_revision in revisions:
            for previous_revision in revisions:
                # we filter out all revisions that are not approved
                # as that's the way the get_previous method does it as well
                # also let's skip comparing the same revisions
                if (not previous_revision.is_approved or
                        current_revision.pk == previous_revision.pk):
                    continue
                # we stick to the first revision that we find
                if previous_revision.created < current_revision.created:
                    current_revision.previous_revision = previous_revision
                    break
        return revisions

    per_page = request.GET.get('limit', 10)

    if not request.user.is_authenticated() and per_page == 'all':
        return render(request, '403.html',
                      {'reason': 'revisions_login_required'}, status=403)

    # Grab revisions, but defer summary and content because they can lead to
    # attempts to cache more than memcached allows.
    all_revisions = (document.revisions.defer('summary', 'content').order_by('created', 'id')
                     .select_related('creator').reverse().transform(get_previous))

    if not all_revisions.exists():
        raise Http404

    if per_page == 'all':
        page = None
        all_revisions = list(all_revisions)
    else:
        try:
            per_page = int(per_page)
        except ValueError:
            per_page = DOCUMENTS_PER_PAGE

        page = paginate(request, all_revisions, per_page)
        all_revisions = list(page.object_list)
    # In order to compare the first revision of a translation, need to insert its parent revision to the list
    # The parent revision should stay at last page in order to compare. So insert only if there are no next page or
    # all revisions are showing
    if (not page or not page.has_next()) and document.parent:
        # *all_revisions are in descending order. so call last() in order to get first revision
        first_rev_based_on = all_revisions[-1].based_on
        # Translation can be orphan so that first revision does not have any english based on. So handle the situation.
        if first_rev_based_on:
            all_revisions.append(first_rev_based_on)

    context = {
        'revisions': all_revisions,
        'document': document,
        'page': page,
    }
    return render(request, 'wiki/list/revisions.html', context)
