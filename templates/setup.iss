{% if preview is sameas true %}
  {% set product = product ~ " Preview" %}
  {% set appid = appid_preview %}
{% else %}
  {% set appid = appid_release %}
{% endif %}

[Setup]
;InfoAfterFile=THANKS.txt
;InfoBeforeFile=WELCOME.txt
AppId={% raw %}{{{% endraw %}{{ appid }}}
AppName={{ product }}
AppPublisher={{ publisher }}
AppPublisherURL={{ publisher_url }}
AppSupportURL={{ support_url }}
AppUpdatesURL={{ updates_url }}
AppVersion={{ version }}
Compression=lzma
DefaultDirName={userpf}\{{ product }}
DefaultGroupName={{ product }}
LicenseFile={{ license }}
OutputBaseFilename={{ name }}
OutputDir={{ output_directory }}
PrivilegesRequired=lowest
SolidCompression=yes

{% if cpu != "x86" %}
ArchitecturesAllowed={{ cpu }}
ArchitecturesInstallIn64BitMode={{ cpu }}
{% endif %}

[Languages]
Name: "english"; \
  MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; \
  Description: {% raw %}"{cm:CreateDesktopIcon}"{% endraw %}; \
  GroupDescription: {% raw %}"{cm:AdditionalIcons}"{% endraw %}; \
  Flags: unchecked

[Files]
{% for file in files %}
Source: "{{ file.0 }}"; \
  DestDir: "{app}{% if file.1 -%}/{{ file.1 }}{% endif %}"; \
  Flags: ignoreversion
{% endfor %}

[Icons]
Name: "{group}\{{ product }}"; \
  Comment: "{{ pitch }}"; \
  Filename: "{app}\{{ program }}"

Name: "{userdesktop}\{{ product }}"; \
  Comment: "{{ pitch }}"; \
  Filename: "{app}\{{ program }}"; \
  Tasks: desktopicon

[Run]

Filename: "{app}\{{ program }}"; \
  Description: "Run {{ product }} {{ version }} now"; \
  Flags: nowait postinstall skipifsilent
