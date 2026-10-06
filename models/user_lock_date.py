import ast
import functools
import types
from datetime import datetime

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_date

EXCLUDED_MODELS = ('user.lock.date', 'res.users', 'res.users.log')

EXCLUDED_METHODS = (
    'read', 'search', 'search_read', 'search_count', 'browse', 'read_group',
    'name_search', 'exists', 'sudo', 'with_context', 'with_user', 'with_env',
)


def _make_create_wrapper(origin):
    @api.model_create_multi
    def create(self, vals_list, **kw):
        records = origin(self, vals_list, **kw)
        # checked after create so computed dates are the real ones;
        # the error rolls back the whole transaction
        self.env['user.lock.date']._check_records(records, 'create')
        return records
    return create


def _make_write_wrapper(origin):
    def write(self, vals, **kw):
        lock = self.env['user.lock.date']
        lock._check_records(self, 'write')   
        result = origin(self, vals, **kw)
        lock._check_records(self, 'write')   
        return result
    return write


def _make_generic_wrapper(name, origin):
    @functools.wraps(origin)
    def wrapper(self, *args, **kwargs):
        self.env['user.lock.date']._check_records(self, name)
        return origin(self, *args, **kwargs)
    return wrapper


class UserLockDate(models.Model):
    _name = 'user.lock.date'
    _description = 'User-Wise Lock Date'
    _order = 'model_id, method_name, lock_date desc, id'

    name = fields.Char(compute='_compute_name')
    user_ids = fields.Many2many(
        'res.users', 'user_lock_date_users_rel', 'rule_id', 'user_id',
        string='Users', required=True)
    model_id = fields.Many2one(
        'ir.model', string='Model', required=True, ondelete='cascade')
    model_name = fields.Char(
        string='Model Name', related='model_id.model', store=True, index=True)
    method_name = fields.Char(
        string='Method Name', required=True,
        help='Python method to restrict, for example create, write, unlink, '
             'action_confirm or action_post.')
    date_field_id = fields.Many2one(
        'ir.model.fields', string='Date Field', required=True,
        ondelete='cascade',
        domain="[('model_id', '=', model_id), ('ttype', 'in', ['date', 'datetime'])]",
        help='The date on the document that is compared with the lock date.')
    lock_date = fields.Date(
        string='Lock Date', required=True,
        help='Documents dated on or before this date are blocked.')
    record_filter = fields.Char(
        string='Record Filter',
        help="Optional domain to limit the rule, for example "
             "[('move_type', '=', 'out_invoice')] for customer invoices only.")
    active = fields.Boolean(default=True)

    @api.depends('model_id', 'method_name', 'lock_date')
    def _compute_name(self):
        for rule in self:
            rule.name = '%s / %s / up to %s' % (
                rule.model_id.name or '', rule.method_name or '',
                rule.lock_date or '')

    @api.onchange('model_id')
    def _onchange_model_id(self):
        self.date_field_id = False

    @api.constrains('user_ids', 'model_id', 'method_name', 'date_field_id',
                    'record_filter')
    def _check_rule(self):
        for rule in self:
            if not rule.user_ids:
                raise ValidationError(self.env._('Select at least one user.'))
            model_name = rule.model_id.model
            if model_name in EXCLUDED_MODELS:
                raise ValidationError(self.env._(
                    'The model %s cannot be locked.', model_name))
            if rule.date_field_id.model_id != rule.model_id:
                raise ValidationError(self.env._(
                    'The date field must belong to the selected model.'))
            method = (rule.method_name or '').strip()
            if (not method or method.startswith('_')
                    or method in EXCLUDED_METHODS
                    or not callable(getattr(self.env[model_name], method, None))):
                raise ValidationError(self.env._(
                    'Method "%(method)s" does not exist on model %(model)s '
                    'or cannot be restricted.',
                    method=method, model=model_name))
            if rule.record_filter:
                try:
                    domain = ast.literal_eval(rule.record_filter)
                    self.env[model_name].search_count(domain)
                except Exception:
                    raise ValidationError(self.env._(
                        'The record filter is not a valid domain.'))

    def _register_hook(self):
        super()._register_hook()
        self._install_patches()

    def _install_patches(self):
        registry = self.env.registry
        keys = {
            (rule.model_name, rule.method_name.strip())
            for rule in self.sudo().search([])
            if rule.model_name and rule.method_name
        }
        for model_name, method in keys:
            if model_name not in registry:
                continue  # model of the rule was uninstalled
            ModelClass = registry[model_name]
            origin = getattr(ModelClass, method, None)
            if origin is None or getattr(origin, '_user_lock_patched', False):
                continue
            if method == 'create':
                wrapper = _make_create_wrapper(origin)
            elif method == 'write':
                wrapper = _make_write_wrapper(origin)
            else:
                wrapper = _make_generic_wrapper(method, origin)
            wrapper._user_lock_patched = True
            setattr(ModelClass, method, wrapper)

    def _remove_patches(self):
        for ModelClass in self.env.registry.values():
            for name, value in list(vars(ModelClass).items()):
                if (isinstance(value, types.FunctionType)
                        and getattr(value, '_user_lock_patched', False)):
                    delattr(ModelClass, name)

    def _update_registry(self):
        """Re-install the patches after a rule changed, and notify workers."""
        if self.env.registry.ready and not self.env.context.get('import_file'):
            self.env.transaction.will_change_registry()
            self._remove_patches()
            self._install_patches()

    @api.model_create_multi
    def create(self, vals_list):
        rules = super().create(vals_list)
        rules._update_registry()
        return rules

    def write(self, vals):
        result = super().write(vals)
        self._update_registry()
        return result

    def unlink(self):
        result = super().unlink()
        self._update_registry()
        return result

    
    @api.model
    def _get_rules(self, model_name, method_name, user):
        return self.sudo().search([
            ('model_name', '=', model_name),
            ('method_name', '=', method_name),
            ('user_ids', 'in', user.id),
        ])

    @api.model
    def _to_date(self, record, value):
        if not value:
            return False
        if isinstance(value, datetime):
            return fields.Datetime.context_timestamp(record, value).date()
        return value

    @api.model
    def _check_records(self, records, method_name):
        """Raise a UserError if the current user is locked for these records."""
        env = records.env
        if not records or env.uid == SUPERUSER_ID or env.context.get('install_mode'):
            return
        rules = self._get_rules(records._name, method_name, env.user)
        for rule in rules:
            targets = records
            if rule.record_filter:
                targets = records.filtered_domain(ast.literal_eval(rule.record_filter))
            fname = rule.date_field_id.name
            for record in targets:
                doc_date = self._to_date(record, record[fname])
                if doc_date and doc_date <= rule.lock_date:
                    raise UserError(env._(
                        "You are not allowed to run '%(method)s' on %(model)s "
                        "dated on or before %(date)s. "
                        "This date is locked for your user.",
                        method=method_name,
                        model=record._description,
                        date=format_date(env, rule.lock_date)))