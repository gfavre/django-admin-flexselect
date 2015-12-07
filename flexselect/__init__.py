from itertools import chain
import hashlib
import json

from django.core.urlresolvers import reverse
from django.forms.widgets import Select, SelectMultiple
from django.utils.encoding import smart_text as smart_unicode
from django.utils.safestring import mark_safe
from django.conf import settings
from django.core.exceptions import ValidationError, ObjectDoesNotExist

EMPTY_CHOICE = ('', '---------')

# Update default settings.
FLEXSELECT = {
    'include_jquery': False,
}

try:
    FLEXSELECT.update(settings.FLEXSELECT)
except AttributeError:
    pass


def choices_from_queryset(queryset):
    """
    Makes choices from a QuerySet in a format that is usable by the
    django.forms.widget.Select widget.

    queryset: An instance of django.db.models.query.QuerySet
    """
    return chain(
        [EMPTY_CHOICE],
        [(o.pk, smart_unicode(o)) for o in queryset],
    )


def choices_from_instance(instance, widget):
    """
    Builds choices from a model instance using the widgets queryset() method.
    If any of the widgets trigger_field fields is not defined on the instance
    or the instance itself is None, None is returned.

    instance: An instance of the model used on the current admin page.
    widget: A widget instance given to the FlexSelectWidget.
    """
    try:
        for trigger_field in widget.trigger_fields:
            getattr(instance, trigger_field)
    except (ObjectDoesNotExist, AttributeError):
        return [('', widget.empty_choices_text(instance))]

    return choices_from_queryset(widget.queryset(instance))


def details_from_instance(instance, widget):
    """
    Builds html from a model instance using the widgets details() method. If
    any of the widgets trigger_field fields is not defined on the instance or
    the instance itself is None, None is returned.

    instance: An instance of the model used on the current admin page.
    widget: A widget instance given to the FlexSelectWidget.
    """
    try:
        for trigger_field in widget.trigger_fields:
            getattr(instance, trigger_field)
        related_instance = getattr(instance, widget.base_field.name)
    except (ObjectDoesNotExist, AttributeError):
        return u''
    return widget.details(related_instance, instance)


def instance_from_request(request, widget):
    """
    Returns a partial instance of the widgets model loading it with values
    from a POST request.
    """
    items = dict(request.POST.items())
    values = {}
    for f in widget.base_field.model._meta.fields:
        if f.name in items:
            try:
                value = f.formfield().to_python(items[f.name])
                if value is not None:
                    values[f.name] = value
            except ValidationError:
                pass
    return widget.base_field.model(**values)


class FlexBaseWidget(object):
    instances = {}
    unique_name = None

    """ Instances of widgets with their hashed names as keys."""

    class Media:
        js = []
        if FLEXSELECT['include_jquery']:
            googlecdn = "https://ajax.googleapis.com/ajax/libs"
            js.append('%s/jquery/1.6.1/jquery.min.js' % googlecdn)
            js.append('%s/jqueryui/1.8.13/jquery-ui.min.js' % googlecdn)
        js.append('flexselect/js/flexselect.js')

    def __init__(self, base_field, modeladmin, request, choice_function=None,
                 *args, **kwargs):
        self.choice_function = choice_function
        self.base_field = base_field
        self.modeladmin = modeladmin
        self.request = request

        self.hashed_name = self._hashed_name()
        FlexSelectWidget.instances[self.hashed_name] = self
        super(FlexBaseWidget, self).__init__(*args, **kwargs)

    def _hashed_name(self):
        """
        Each widget will be unique by the name of the field and the class name
        of the model admin.
        """
        if self.unique_name is not None:
            return self.unique_name
        else:
            salted_string = ''.join([
                settings.SECRET_KEY,
                self.base_field.name,
                self.modeladmin.__class__.__name__,
            ]).encode('utf-8')
            return "_%s" % hashlib.sha1(salted_string).hexdigest()

    def _get_instance(self):
        """
        Returns a model instance from the url in the admin page.
        """
        if self.request.method == 'POST':
            return instance_from_request(self.request, self)
        else:
            try:
                path = self.request.META['PATH_INFO'].strip('/')
                object_id = int(path.split('/').pop())
                return self.modeladmin.get_object(self.request, object_id)
            except ValueError:
                return None

    def _build_js(self):
        """
        Adds the widgets hashed_name as the key with an array of its
        trigger_fields as the value to flexselect.selects.
        """
        return """
        <script>
            var flexselect = flexselect || {};
            flexselect.fields = flexselect.fields || {};
            flexselect.url = %s;
            flexselect.fields.%s = %s;
        </script>""" % (
            reverse('flexselect_field_changed'),
            self.hashed_name,
            json.dumps({
                'base_field': self.base_field.name,
                'trigger_fields': self.trigger_fields,
            }),
        )

    def render(self, name, value, attrs=None, choices=(), *args, **kwargs):
        """
        Overrides. Reduces the choices by calling the widgets queryset()
        method and adds a details <span> that is filled with the widgets
        details() method.
        """
        instance = self._get_instance()
        if self.choice_function:
            self.choices = self.choice_function(instance)
        else:
            self.choices = choices_from_instance(instance, self)
        return mark_safe(''.join([
            super(self, FlexBaseWidget).render(
                name, value, attrs=attrs,
                *args, **kwargs
            ),
            self._build_js(),
            '<span class="flexselect_details">',
            details_from_instance(instance, self),
            '</span>',
        ]))

    # Methods and properties that must be implemented.

    trigger_fields = []

    def details(self, base_field_instance, instance):
        raise NotImplementedError

    def queryset(self, instance):
        raise NotImplementedError

    def empty_choices_text(self, instance):
        raise NotImplementedError


class FlexSelectWidget(FlexBaseWidget, Select):
    pass


class FlexSelectMultipleWidget(FlexBaseWidget, SelectMultiple):
    def __init__(self, *args, **kwargs):
        super(FlexSelectMultipleWidget, self).__init__(*args, **kwargs)
