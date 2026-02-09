from setuptools import setup, find_packages

setup(
    name="email_services",
    version="0.1",
    packages=find_packages(),
    entry_points={
        "email_service.plugins": [
            "gmail = email_services.plugins.google.plugin:GmailPlugin",
            "sendgrid = email_services.plugins.sendgrid.plugin:SendgridPlugin",
            "amazonsns = email_services.plugins.amazon.plugin:AmazonSNS",
        ]
    },
)
