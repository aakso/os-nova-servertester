from __future__ import print_function, unicode_literals

import base64
import yaml

class CloudConfigGenerator(object):
    def __init__(self):
        self.write_files = []
        self.runcmd = []

    def add_write_file(self, path, content_or_file, mode='0640'):
        if hasattr(content_or_file, 'read'):
            content = content_or_file.read()
        else:
            content = content_or_file
        self.write_files.append(
            dict(
                encoding='b64',
                content=base64.b64encode(content),
                permissions=mode,
                path=path,
            )
        )

    def add_runcmd(self, *cmd):
        self.runcmd.append(cmd)

    def generate(self):
        return "#cloud-config\n" + yaml.safe_dump(dict(
            write_files=self.write_files,
            runcmd=self.runcmd,
        ))
