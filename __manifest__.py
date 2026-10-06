{
    'name': 'User-Wise Lock Date Access',
    'version': '20.0.2.1',
    'summary': 'Block selected users from backdated transactions on any model and method',
    'depends': ['base'],
    'data': [
        'security/ir.access.csv',
        'views/lock_date_views.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
    'author': 'Prixgen',
}