__all__ = ['Circulars']

import sqlalchemy as sa
from sqlalchemy.orm import relationship
from sqlalchemy.orm import deferred
from sqlalchemy.ext.hybrid import hybrid_property

import requests
from bs4 import BeautifulSoup
import csv
import re

import gcn
import lxml

from baselayer.app.models import Base, DBSession, AccessibleIfUserMatches

class Circular(Base):
    """Circular information, including circular number, link, title, GCN code."""

    update = delete = AccessibleIfUserMatches('sent_by')

    meta = sa.MetaData()

    circulars = sa.Table(
        'circulars', meta,
        sa.Column('number', sa.Integer, primary_key=True),
        sa.Column('link', sa.String),
        sa.Column('title', sa.String),
        sa.Column('code', sa.String)
    )