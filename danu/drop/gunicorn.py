"""gunicorn's settings for the data drop, read by ``danu-drop.service`` as
``-c python:danu.drop.gunicorn`` - here rather than on its command line,
where systemd takes every % for one of its own specifiers.

The access log names the mapper's address, not nginx's. Every request
reaches the drop from api over the VPN, so gunicorn's own idea of the client
is api; nginx sets ``X-Forwarded-For`` to the address that reached it.
Sets, not appends: ogf-server-scripts' ``snippets/ogf-data.conf`` has
``proxy_set_header X-Forwarded-For $remote_addr``, which overwrites whatever
a client sent - ``$proxy_add_x_forwarded_for`` would append, and the header
would be a list a client began. The drop is reached only from api, over the
VPN (``DROP_BIND``, and util's ufw).
"""

access_log_format = '%({x-forwarded-for}i)s "%(r)s" %(s)s %(b)s %(L)ss "%(a)s"'
