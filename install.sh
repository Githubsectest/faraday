#!/bin/bash
###
## Faraday Penetration Test IDE
## Copyright (C) 2018  Infobyte LLC (http://www.infobytesec.com/)
## See the file 'doc/LICENSE' for the license information
###

if [ $EUID -ne 0 ]; then
 echo "You must be root."
 exit 1
fi

apt-get update

#Install community dependencies
for pkg in build-essential python-setuptools python-pip python-dev libpq-dev libffi-dev gir1.2-gtk-3.0 gir1.2-vte-2.91 python-gobject zsh curl python-psycopg2 ; do
    apt-get install -y $pkg
done

pip2 install -r requirements_server.txt
pip2 install -r requirements.txt

echo "You can now run Faraday, enjoy!"