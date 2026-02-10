from setuptools import setup, find_packages

setup(
    name="email_services",
    version="0.1",
    packages=find_packages(),
    entry_points={
        "email_service.plugins": [
            "gmail = email_services.plugins.google.plugin:GoogleCloudGmailPlugin",
            "sendgrid = email_services.plugins.sendgrid.plugin:SendGridPlugin",
            "customSMTP = email_services.plugins.customSMTP.plugin:CustomSMTPPlugin",
            "amazonsns = email_services.plugins.amazon.plugin:AmazonSNSPlugin",
            "mailgun = email_services.plugins.mailgun.plugin:MailgunPlugin", 
        ]
    },
)
