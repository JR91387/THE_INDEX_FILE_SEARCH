-- SPDX-License-Identifier: MIT
-- seed_content_rules.sql -- how folder content types are detected. Re-applied on every init/upgrade.
-- Extension rules count bytes per type; marker rules (weight 10) identify a folder outright.
INSERT OR IGNORE INTO ref_content_rule (content_type_id, match_kind, pattern, weight)
SELECT t.id, v.column2, v.column3, v.column4 FROM (VALUES
 ('documents','ext','.pdf',1), ('documents','ext','.doc',1), ('documents','ext','.docx',1), ('documents','ext','.odt',1), ('documents','ext','.rtf',1), ('documents','ext','.txt',1),
 ('documents','ext','.md',1), ('documents','ext','.xls',1), ('documents','ext','.xlsx',1), ('documents','ext','.ods',1), ('documents','ext','.ppt',1), ('documents','ext','.pptx',1),
 ('documents','ext','.odp',1), ('documents','ext','.csv',1), ('documents','ext','.epub',1), ('photos','ext','.jpg',1), ('photos','ext','.jpeg',1), ('photos','ext','.png',1),
 ('photos','ext','.gif',1), ('photos','ext','.heic',1), ('photos','ext','.heif',1), ('photos','ext','.webp',1), ('photos','ext','.tif',1), ('photos','ext','.tiff',1),
 ('photos','ext','.raw',1), ('photos','ext','.cr2',1), ('photos','ext','.nef',1), ('photos','ext','.dng',1), ('photos','ext','.bmp',1), ('photos','ext','.svg',1),
 ('video','ext','.mp4',1), ('video','ext','.mkv',1), ('video','ext','.mov',1), ('video','ext','.avi',1), ('video','ext','.webm',1), ('video','ext','.m4v',1),
 ('video','ext','.wmv',1), ('video','ext','.mpg',1), ('video','ext','.mpeg',1), ('audio','ext','.mp3',1), ('audio','ext','.flac',1),
 ('audio','ext','.wav',1), ('audio','ext','.ogg',1), ('audio','ext','.m4a',1), ('audio','ext','.aac',1), ('audio','ext','.opus',1), ('audio','ext','.wma',1),
 ('code_repo','ext','.py',1), ('code_repo','ext','.rs',1), ('code_repo','ext','.js',1), ('code_repo','ext','.ts',1), ('code_repo','ext','.tsx',1), ('code_repo','ext','.jsx',1),
 ('code_repo','ext','.go',1), ('code_repo','ext','.c',1), ('code_repo','ext','.h',1), ('code_repo','ext','.cpp',1), ('code_repo','ext','.java',1), ('code_repo','ext','.rb',1),
 ('code_repo','ext','.php',1), ('code_repo','ext','.sh',1), ('code_repo','ext','.sql',1), ('code_repo','ext','.html',1), ('code_repo','ext','.css',1), ('code_repo','ext','.svelte',1),
 ('code_repo','ext','.vue',1), ('database','ext','.sqlite',1), ('database','ext','.sqlite3',1), ('database','ext','.db',1), ('database','ext','.mdb',1), ('database','ext','.ldf',1),
 ('database','ext','.mdf',1), ('database','ext','.ibd',1), ('db_dump','ext','.dump',1), ('db_dump','ext','.bak',1), ('db_dump','ext','.sql.gz',1), ('db_dump','ext','.pgdump',1),
 ('archive','ext','.zip',1), ('archive','ext','.tar',1), ('archive','ext','.gz',1), ('archive','ext','.tgz',1), ('archive','ext','.bz2',1), ('archive','ext','.xz',1),
 ('archive','ext','.zst',1), ('archive','ext','.7z',1), ('archive','ext','.rar',1), ('logs','ext','.log',1), ('logs','ext','.journal',1), ('config','ext','.conf',1),
 ('config','ext','.cfg',1), ('config','ext','.ini',1), ('config','ext','.toml',1), ('config','ext','.yaml',1), ('config','ext','.yml',1), ('config','ext','.json',1),
 ('config','ext','.env',1), ('config','ext','.service',1), ('config','ext','.timer',1), ('vm_image','ext','.iso',1), ('vm_image','ext','.img',1), ('vm_image','ext','.qcow2',1),
 ('vm_image','ext','.vmdk',1), ('vm_image','ext','.vhd',1), ('vm_image','ext','.vhdx',1), ('vm_image','ext','.vdi',1), ('code_repo','marker','.git',10), ('code_repo','marker','Cargo.toml',10),
 ('code_repo','marker','package.json',10), ('code_repo','marker','pyproject.toml',10), ('code_repo','marker','go.mod',10), ('database','marker','PG_VERSION',10), ('database','marker','ibdata1',10), ('database','marker','mysql.ibd',10),
 ('cache','marker','CACHEDIR.TAG',10), ('cache','marker','node_modules',10), ('cache','marker','__pycache__',10), ('cache','marker','.cache',10), ('container_volume','marker','_data',10)
) AS v JOIN ref_content_type t ON t.code = v.column1;
