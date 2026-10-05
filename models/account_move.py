from odoo import api, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # checked after create so computed dates are the real ones;
        # the error rolls back the whole transaction
        self.env['user.lock.date']._check_records(records, 'create')
        return records

    def write(self, vals):
        lock = self.env['user.lock.date']
        lock._check_records(self, 'write')  # current (old) date
        result = super().write(vals)
        lock._check_records(self, 'write')  # new date after the change
        return result

    def unlink(self):
        self.env['user.lock.date']._check_records(self, 'unlink')
        return super().unlink()