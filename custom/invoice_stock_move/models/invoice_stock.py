# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2019-TODAY Cybrosys Technologies(<https://www.cybrosys.com>).
#    Author: Saritha Sahadevan @cybrosys(odoo@cybrosys.com)
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
#    (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from odoo.exceptions import UserError
from odoo import models, fields, api, _
import logging
_logger = logging.getLogger(__name__)
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT, float_compare, float_round
#acount move
class InvoiceStockMove(models.Model):
    _inherit = 'account.move'

    @api.model
    def _default_warehouse_id(self):
        # !!! Any change to the default value may have to be repercuted
        # on _init_column() below.
        #return self.env.user._get_default_warehouse_id()
        _logger.info("self.env['stock.warehouse'].sudo().search([('is_sale_storage','=',True)],limit=1).id %s",self.env['stock.warehouse'].sudo().search([('is_sale_storage','=',True)],limit=1).id)
        return self.env['stock.warehouse'].sudo().search([('is_sale_storage','=',True)],limit=1).id
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Almacen',
        default=_default_warehouse_id)

    


    def _get_stock_type_ids(self):
        data = self.env['stock.picking.type'].search([])

        if self._context.get('default_move_type') == 'out_invoice':
            for line in data:
                if line.code == 'outgoing':
                    return line
        if self._context.get('default_move_type') == 'in_invoice':
            for line in data:
                if line.code == 'incoming':
                    return line
        if self._context.get('default_move_type') == 'out_refund':
            for line in data:
                if line.code == 'incoming':
                    return line
        if self._context.get('default_move_type') == 'in_refund':
            for line in data:
                if line.code == 'outgoing':
                    return line
        #en caso de que context no tenga nada dentro de los tipos permitidos retornar por defecto outgoing
        if self._context.get('default_move_type') not in ['out_invoice','in_invoice','out_refund','in_refund']:
            for line in data:
                if line.code == 'outgoing':
                    return line
    picking_count = fields.Integer(string="Count",copy=False)
    invoice_picking_id = fields.Many2one('stock.picking', string="Picking Id",copy=False)

    picking_type_id = fields.Many2one('stock.picking.type', 'Picking Type',
                                      default=_get_stock_type_ids,
                                      help="This will determine picking type of incoming shipment",copy=False)
    @api.depends('invoice_origin')
    def check_pick_order(self):
        for i in self.filtered(lambda r: r.is_sale_document()):
            have_pick_order = False
            if i.invoice_origin:
                order = self.env['sale.order'].sudo().search([('name','=',i.invoice_origin)])
                if any(order.filtered(lambda s: s.picking_ids and len(s.picking_ids)>0)):
                    have_pick_order = True
            i.have_pick_order = have_pick_order

    state = fields.Selection([
        ('draft', 'Draft'),
        ('proforma', 'Pro-forma'),
        ('proforma2', 'Pro-forma'),
        ('posted', 'Posted'),
        ('post', 'Post'),
        ('cancel', 'Cancelled'),
        ('done', 'Received'),
    ], string='Status', index=True, readonly=True, default='draft',
        track_visibility='onchange', copy=False)

    have_pick_order = fields.Boolean(string='Tiene pick de orden',compute="check_pick_order",store=True)
    def button_draft(self):
        if any(m.invoice_picking_id and m.invoice_picking_id.state !='cancel' for m in self):
            raise UserError("No puedes cambiar a borrador una factura con orden de entrega sin cancelar.")
        return super(InvoiceStockMove, self).button_draft()

    def button_cancel(self):
        if any(m.invoice_picking_id and m.invoice_picking_id.state !='cancel' for m in self):
            raise UserError("No puedes cancelar una factura con orden de entrega sin cancelar.")
        return super(InvoiceStockMove, self).button_cancel()

    def action_stock_move(self):
        self.ensure_one()
        if not self.picking_type_id:
            raise UserError(_(
                " Por favor selecciona un tipo de picking"))
        #si tiene saldo deudor y la configuracion NO permite generar picking con saldo deudor
        if self.amount_residual >0 and not self.env['ir.config_parameter'].sudo().get_param('picking_with_residual'):
            raise UserError("La factura no debe tener importe adeudado para emitir la orden de inventario")
        for order in self:
            for l in order.invoice_line_ids:
                l._confirm_check_availability_invoice()
            if not self.invoice_picking_id:
                pick = {}
                if self.picking_type_id.code == 'outgoing':
                    pick = {
                        'picking_type_id': self.picking_type_id.id,
                        'partner_id': self.partner_id.id,
                        'origin': self.name,
                        'location_dest_id': self.partner_id.property_stock_customer.id,
                        'location_id': self.picking_type_id.default_location_src_id.id,
                        'move_type': 'direct'
                    }
                if self.picking_type_id.code == 'incoming':
                    pick = {
                        'picking_type_id': self.picking_type_id.id,
                        'partner_id': self.partner_id.id,
                        'origin': self.name,
                        'location_dest_id': self.picking_type_id.default_location_dest_id.id,
                        'location_id': self.partner_id.property_stock_supplier.id,
                        'move_type': 'direct'
                    }

                picking = self.env['stock.picking'].sudo().create(pick)
                self.invoice_picking_id = picking.id
                self.picking_count = len(picking)
                moves = order.invoice_line_ids.filtered(
                    lambda r: r.product_id.type in ['product', 'consu']).sudo()._create_stock_moves(picking)
                move_ids = moves.sudo()._action_confirm()
                move_ids.sudo()._action_assign()

    def action_view_picking(self):
        action = self.env.ref('stock.action_picking_tree_ready')
        result = action.read()[0]
        result.pop('id', None)
        result['context'] = {}
        result['domain'] = [('id', '=', self.invoice_picking_id.id)]
        pick_ids = sum([self.invoice_picking_id.id])
        if pick_ids:
            res = self.env.ref('stock.view_picking_form', False)
            result['views'] = [(res and res.id or False, 'form')]
            result['res_id'] = pick_ids or False
        return result

    def _reverse_moves(self, default_values_list=None, cancel=False):
        ''' Reverse a recordset of account.move.
        If cancel parameter is true, the reconcilable or liquidity lines
        of each original move will be reconciled with its reverse's.

        :param default_values_list: A list of default values to consider per move.
                                    ('type' & 'reversed_entry_id' are computed in the method).
        :return:                    An account.move recordset, reverse of the current self.
        '''

        if self.picking_type_id.code == 'outgoing':
            data = self.env['stock.picking.type'].search(
                [('company_id', '=', self.company_id.id), ('code', '=', 'incoming')], limit=1)
            self.picking_type_id = data.id
        elif self.picking_type_id.code == 'incoming':
            data = self.env['stock.picking.type'].search(
                [('company_id', '=', self.company_id.id), ('code', '=', 'outgoing')], limit=1)
            self.picking_type_id = data.id
        reverse_moves = super(InvoiceStockMove, self)._reverse_moves()
        return reverse_moves


class SupplierInvoiceLine(models.Model):
    _inherit = 'account.move.line'

    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Almacen',
        related='move_id.warehouse_id',store=True)

    alert_qty = fields.Boolean(string='Alerta de Cantidad')

    @api.onchange('quantity', 'product_id', 'warehouse_id')
    def _onchange_product_id_check_availability(self):
        if not self.product_id or not self.quantity or not self.warehouse_id:
            return {}
        if self.product_id.type == 'product' and self.warehouse_id and self.move_id.is_inbound():
            _logger.info("self.product_id.free_qty arriba %s",self.product_id.free_qty)
            precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
            product = self.product_id.with_context(
                warehouse=self.warehouse_id.id,
                lang=self.move_id.partner_id.lang or self.env.user.lang or 'en_US'
            )
            #buscar cantidad por almacen elegido
            #product_qty = self.product_uom._compute_quantity(self.product_uom_qty, self.product_id.uom_id)
            #if product.virtual_available < self.quantity:
            #for warehouse in self.env['stock.warehouse'].search([]):
            #    quantity = self.product_id.with_context(warehouse=warehouse.id).free_qty
            #    _logger.info("quantity %s",quantity)
            if product.free_qty < self.quantity:
                another_have = False
                self.alert_qty = True
                message =  _('Planeas vender %s %s de %s pero solo tienes %s %s disponibles en %s.') % \
                        (self.quantity, self.product_id.uom_id.name, self.product_id.name, product.free_qty, product.uom_id.name, self.warehouse_id.name)
                # We check if some products are available in other warehouses.
                _logger.info("self.product_id.free_qty %s",self.product_id.free_qty)
                if product.free_qty < self.product_id.free_qty:
                    message += _('\nExisten %s %s disponible entre todos los almacenes.\n\n') % \
                            (self.product_id.free_qty, product.uom_id.name)
                    for warehouse in self.env['stock.warehouse'].search([]):
                        quantity = self.product_id.with_context(warehouse=warehouse.id).free_qty
                        if quantity > 0:
                            message += "%s: %s %s\n" % (warehouse.name, quantity, self.product_id.uom_id.name)
                #los demas almacenes si tienen
                if self.quantity <= self.product_id.free_qty:
                    another_have = True
                warning_mess = {
                    'title': _('No hay suficiente inventario!'),
                    'message' : message
                }
                #si otro almacen no tiene mandar a 0
                if not another_have:
                    self.quantity = 0
                return {'warning': warning_mess}
            else:
                self.alert_qty = False
        return {}


    #misma validacion pero en este caso se retorna un raise exepcion para detener la operacion
    def _confirm_check_availability_invoice(self):
        if not self.product_id or not self.quantity or not self.warehouse_id:
            raise UserError("Producto, cantidad y ALmacen son obligatorios")
        if self.product_id.type == 'product' and self.warehouse_id and self.move_id.is_inbound():
            _logger.info("self.product_id.free_qty arriba %s",self.product_id.free_qty)
            precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
            product = self.product_id.with_context(
                warehouse=self.warehouse_id.id,
                lang=self.move_id.partner_id.lang or self.env.user.lang or 'en_US'
            )
            #buscar cantidad por almacen elegido
            #product_qty = self.product_uom._compute_quantity(self.product_uom_qty, self.product_id.uom_id)
            #if product.virtual_available < self.quantity:
            #for warehouse in self.env['stock.warehouse'].search([]):
            #    quantity = self.product_id.with_context(warehouse=warehouse.id).free_qty
            #    _logger.info("quantity %s",quantity)
            if product.free_qty < self.quantity:
                another_have = False
                message =  _('Planeas vender %s %s de %s pero solo tienes %s %s disponibles en %s.') % \
                        (self.quantity, self.product_id.uom_id.name, self.product_id.name, product.free_qty, product.uom_id.name, self.warehouse_id.name)
                # We check if some products are available in other warehouses.
                _logger.info("self.product_id.free_qty %s",self.product_id.free_qty)
                if product.free_qty < self.product_id.free_qty:
                    message += _('\nExisten %s %s disponible entre todos los almacenes.\n\n') % \
                            (self.product_id.free_qty, product.uom_id.name)
                    for warehouse in self.env['stock.warehouse'].search([]):
                        quantity = self.product_id.with_context(warehouse=warehouse.id).free_qty
                        if quantity > 0:
                            message += "%s: %s %s\n" % (warehouse.name, quantity, self.product_id.uom_id.name)
                    another_have = True
                warning_mess = {
                    'title': _('No hay suficiente inventario!'),
                    'message' : message
                }
                raise UserError(message)
        return True

    def _create_stock_moves(self, picking):
        moves = self.env['stock.move']
        done = self.env['stock.move'].browse()
        for line in self:
            price_unit = line.price_unit
            if picking.picking_type_id.code == 'outgoing':
                template = {
                    'name': line.name or '',
                    'product_id': line.product_id.id,
                    'product_uom': line.product_uom_id.id,
                    'location_id': picking.picking_type_id.default_location_src_id.id,
                    'location_dest_id': line.move_id.partner_id.property_stock_customer.id,
                    'picking_id': picking.id,
                    'state': 'draft',
                    'company_id': line.move_id.company_id.id,
                    'price_unit': price_unit,
                    'picking_type_id': picking.picking_type_id.id,
                    'route_ids': 1 and [
                        (6, 0, [x.id for x in self.env['stock.location.route'].search([('id', 'in', (2, 3))])])] or [],
                    'warehouse_id': picking.picking_type_id.warehouse_id.id,
                }
            if picking.picking_type_id.code == 'incoming':
                template = {
                    'name': line.name or '',
                    'product_id': line.product_id.id,
                    'product_uom': line.product_uom_id.id,
                    'location_id': line.move_id.partner_id.property_stock_supplier.id,
                    'location_dest_id': picking.picking_type_id.default_location_dest_id.id,
                    'picking_id': picking.id,
                    'state': 'draft',
                    'company_id': line.move_id.company_id.id,
                    'price_unit': price_unit,
                    'picking_type_id': picking.picking_type_id.id,
                    'route_ids': 1 and [
                        (6, 0, [x.id for x in self.env['stock.location.route'].search([('id', 'in', (2, 3))])])] or [],
                    'warehouse_id': picking.picking_type_id.warehouse_id.id,
                }
            diff_quantity = line.quantity
            tmp = template.copy()
            tmp.update({
                'product_uom_qty': diff_quantity,
            })
            template['product_uom_qty'] = diff_quantity
            done += moves.create(template)
        return done