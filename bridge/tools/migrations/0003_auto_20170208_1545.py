# -*- coding: utf-8 -*-
# Generated by Django 1.10.5 on 2017-02-08 12:45
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tools', '0002_calllogs'),
    ]

    operations = [
        migrations.AlterField(
            model_name='calllogs',
            name='enter_time',
            field=models.DecimalField(decimal_places=4, max_digits=14),
        ),
        migrations.AlterField(
            model_name='calllogs',
            name='execution_time',
            field=models.DecimalField(decimal_places=4, max_digits=14),
        ),
        migrations.AlterField(
            model_name='calllogs',
            name='return_time',
            field=models.DecimalField(decimal_places=4, max_digits=14),
        ),
    ]