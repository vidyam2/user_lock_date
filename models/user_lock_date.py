import ast
from datetime import datetime

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_date

# Models where the lock is enforced. To support another model, add it here
# and add create/write/unlink overrides for it (see models/account_move.py).
SUPPORTED_MODELS = ['account.move']

ACTION_LABELS = {'create': 'create', 'write': 'edit', 'unlink': 'delete'}


class UserLockDate(models.Model):
    _name = 'user.lock.date'
    _description = 'User-Wise Lock Date'
    _order = 'model_id, lock_date desc, id'

    name = fields.Char(compute='_compute_name')
    user_ids = fields.Many2many(
        'res.users', 'user_lock_date_users_rel', 'rule_id', 'user_id',
        string='Users', required=True)
    model_id = fields.Many2one(
        'ir.model', string='Model', required=True, ondelete='cascade',
        domain=[('model', 'in', SUPPORTED_MODELS)])
    method = fields.Selection(
        [('create', 'Create'), ('write', 'Edit'), ('unlink', 'Delete')],
        string='Method', required=True, default='create')
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

    @api.depends('model_id', 'method', 'lock_date')
    def _compute_name(self):
        for rule in self:
            rule.name = '%s / %s / up to %s' % (
                rule.model_id.name or '', rule.method or '', rule.lock_date or '')

    @api.onchange('model_id')
    def _onchange_model_id(self):
        self.date_field_id = False
        if self.model_id:
            self.date_field_id = self.env['ir.model.fields'].search([
                ('model_id', '=', self.model_id.id), ('name', '=', 'date'),
            ], limit=1)

    @api.constrains('user_ids', 'model_id', 'date_field_id', 'record_filter')
    def _check_rule(self):
        for rule in self:
            if not rule.user_ids:
                raise ValidationError(self.env._('Select at least one user.'))
            if rule.model_id.model not in SUPPORTED_MODELS:
                raise ValidationError(self.env._(
                    'The lock is only available for: %s',
                    ', '.join(SUPPORTED_MODELS)))
            if rule.date_field_id.model_id != rule.model_id:
                raise ValidationError(self.env._(
                    'The date field must belong to the selected model.'))
            if rule.record_filter:
                try:
                    domain = ast.literal_eval(rule.record_filter)
                    self.env[rule.model_id.model].search_count(domain)
                except Exception:
                    raise ValidationError(self.env._(
                        'The record filter is not a valid domain.'))

    # ------------------------------------------------------------------
    # Enforcement
    # ------------------------------------------------------------------
    @api.model
    def _get_rules(self, model_name, method, user):
        return self.sudo().search([
            ('model_id.model', '=', model_name),
            ('method', '=', method),
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
    def _check_records(self, records, method):
        """Raise a UserError if the current user is locked for these records."""
        env = records.env
        if not records or env.uid == SUPERUSER_ID or env.context.get('install_mode'):
            return
        rules = self._get_rules(records._name, method, env.user)
        for rule in rules:
            targets = records
            if rule.record_filter:
                targets = records.filtered_domain(ast.literal_eval(rule.record_filter))
            fname = rule.date_field_id.name
            for record in targets:
                doc_date = self._to_date(record, record[fname])
                if doc_date and doc_date <= rule.lock_date:
                    raise UserError(env._(
                        "You are not allowed to %(action)s %(model)s "
                        "dated on or before %(date)s. This date is locked for your user.",
                        action=ACTION_LABELS[method],
                        model=record._description,
                        date=format_date(env, rule.lock_date)))