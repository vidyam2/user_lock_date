{
    'name': 'User-Wise Lock Date Access',
    'version': '20.0.1.0',
    'summary': 'Block selected users from backdated transactions',
    'depends': ['base', 'account'],
    'data': [
        'security/ir.access.csv',
        'views/lock_date_views.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
    'author': 'Prixgen',
}