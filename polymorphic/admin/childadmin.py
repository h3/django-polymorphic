"""
The child admin displays the change/delete view of the subclass model.
"""
from django.contrib import admin
from django.core.urlresolvers import resolve
from django.utils import six
from django.utils.translation import ugettext_lazy as _

from .helpers import PolymorphicInlineSupportMixin


class ParentAdminNotRegistered(RuntimeError):
    "The admin site for the model is not registered."
    pass


class PolymorphicChildModelAdmin(admin.ModelAdmin):
    """
    The *optional* base class for the admin interface of derived models.

    This base class defines some convenience behavior for the admin interface:

    * It corrects the breadcrumbs in the admin pages.
    * It adds the base model to the template lookup paths.
    * It allows to set ``base_form`` so the derived class will automatically include other fields in the form.
    * It allows to set ``base_fieldsets`` so the derived class will automatically display any extra fields.

    The ``base_model`` attribute must be set.
    """
    base_model = None
    base_form = None
    base_fieldsets = None
    extra_fieldset_title = _("Contents")  # Default title for extra fieldset
    show_in_index = False

    def get_form(self, request, obj=None, **kwargs):
        # The django admin validation requires the form to have a 'class Meta: model = ..'
        # attribute, or it will complain that the fields are missing.
        # However, this enforces all derived ModelAdmin classes to redefine the model as well,
        # because they need to explicitly set the model again - it will stick with the base model.
        #
        # Instead, pass the form unchecked here, because the standard ModelForm will just work.
        # If the derived class sets the model explicitly, respect that setting.
        kwargs.setdefault('form', self.base_form or self.form)

        # prevent infinite recursion in django 1.6+
        if not getattr(self, 'declared_fieldsets', None):
            kwargs.setdefault('fields', None)

        return super(PolymorphicChildModelAdmin, self).get_form(request, obj, **kwargs)

    def get_model_perms(self, request):
        match = resolve(request.path)

        if not self.show_in_index and match.app_name == 'admin' and match.url_name in ('index', 'app_list'):
            return {'add': False, 'change': False, 'delete': False}
        return super(PolymorphicChildModelAdmin, self).get_model_perms(request)

    @property
    def change_form_template(self):
        opts = self.model._meta
        app_label = opts.app_label

        # Pass the base options
        base_opts = self.base_model._meta
        base_app_label = base_opts.app_label

        return [
            "admin/%s/%s/change_form.html" % (app_label, opts.object_name.lower()),
            "admin/%s/change_form.html" % app_label,
            # Added:
            "admin/%s/%s/change_form.html" % (base_app_label, base_opts.object_name.lower()),
            "admin/%s/change_form.html" % base_app_label,
            "admin/polymorphic/change_form.html",
            "admin/change_form.html"
        ]

    @property
    def delete_confirmation_template(self):
        opts = self.model._meta
        app_label = opts.app_label

        # Pass the base options
        base_opts = self.base_model._meta
        base_app_label = base_opts.app_label

        return [
            "admin/%s/%s/delete_confirmation.html" % (app_label, opts.object_name.lower()),
            "admin/%s/delete_confirmation.html" % app_label,
            # Added:
            "admin/%s/%s/delete_confirmation.html" % (base_app_label, base_opts.object_name.lower()),
            "admin/%s/delete_confirmation.html" % base_app_label,
            "admin/polymorphic/delete_confirmation.html",
            "admin/delete_confirmation.html"
        ]

    @property
    def object_history_template(self):
        opts = self.model._meta
        app_label = opts.app_label

        # Pass the base options
        base_opts = self.base_model._meta
        base_app_label = base_opts.app_label

        return [
            "admin/%s/%s/object_history.html" % (app_label, opts.object_name.lower()),
            "admin/%s/object_history.html" % app_label,
            # Added:
            "admin/%s/%s/object_history.html" % (base_app_label, base_opts.object_name.lower()),
            "admin/%s/object_history.html" % base_app_label,
            "admin/polymorphic/object_history.html",
            "admin/object_history.html"
        ]

    def _get_parent_admin(self):
        # this returns parent admin instance on which to call response_post_save methods
        parent_model = self.model._meta.get_field('polymorphic_ctype').model
        if parent_model == self.model:
            # when parent_model is in among child_models, just return super instance
            return super(PolymorphicChildModelAdmin, self)

        try:
            return self.admin_site._registry[parent_model]
        except KeyError:
            raise ParentAdminNotRegistered("No parent admin was registered for a '{0}' model.".format(parent_model))

    def response_post_save_add(self, request, obj):
        return self._get_parent_admin().response_post_save_add(request, obj)

    def response_post_save_change(self, request, obj):
        return self._get_parent_admin().response_post_save_change(request, obj)

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        context.update({
            'base_opts': self.base_model._meta,
        })
        return super(PolymorphicChildModelAdmin, self).render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)

    def delete_view(self, request, object_id, context=None):
        extra_context = {
            'base_opts': self.base_model._meta,
        }
        return super(PolymorphicChildModelAdmin, self).delete_view(request, object_id, extra_context)

    def history_view(self, request, object_id, extra_context=None):
        # Make sure the history view can also display polymorphic breadcrumbs
        context = {
            'base_opts': self.base_model._meta,
        }
        if extra_context:
            context.update(extra_context)
        return super(PolymorphicChildModelAdmin, self).history_view(request, object_id, extra_context=context)


    # ---- Extra: improving the form/fieldset default display ----

    def get_fieldsets(self, request, obj=None):
        # If subclass declares fieldsets, this is respected
        if (hasattr(self, 'declared_fieldset') and self.declared_fieldsets) \
           or not self.base_fieldsets:
            return super(PolymorphicChildModelAdmin, self).get_fieldsets(request, obj)

        # Have a reasonable default fieldsets,
        # where the subclass fields are automatically included.
        other_fields = self.get_subclass_fields(request, obj)

        if other_fields:
            return (
                self.base_fieldsets[0],
                (self.extra_fieldset_title, {'fields': other_fields}),
            ) + self.base_fieldsets[1:]
        else:
            return self.base_fieldsets

    def get_subclass_fields(self, request, obj=None):
        # Find out how many fields would really be on the form,
        # if it weren't restricted by declared fields.
        exclude = list(self.exclude or [])
        exclude.extend(self.get_readonly_fields(request, obj))

        # By not declaring the fields/form in the base class,
        # get_form() will populate the form with all available fields.
        form = self.get_form(request, obj, exclude=exclude)
        subclass_fields = list(six.iterkeys(form.base_fields)) + list(self.get_readonly_fields(request, obj))

        # Find which fields are not part of the common fields.
        for fieldset in self.base_fieldsets:
            for field in fieldset[1]['fields']:
                try:
                    subclass_fields.remove(field)
                except ValueError:
                    pass   # field not found in form, Django will raise exception later.
        return subclass_fields
