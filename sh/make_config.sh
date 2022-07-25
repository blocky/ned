#!/usr/bin/env bash

set -e

ID_RSA="id_rsa"
ID_RSA_PUB_PEM="${ID_RSA}.pub.pem"

function make_target_path()
{
    local this_dir="$(dirname "$(realpath "$0")")"
    local target="$this_dir/../gateway/config/config.toml"
    if [ -f "$target" ]; then
        echo "Aborting run, $target exists." >&2
        exit 1
    fi

    echo "$target"
}

function create_keys() {
    local tmp_dir=$(mktemp -d -t bky-seq-gateway-XXXXXXXXXX)

    cd ${tmp_dir}
    ssh-keygen -q -N "" -t rsa -f ${tmp_dir}/${ID_RSA} -m pem
    ssh-keygen -q -N "" -f $ID_RSA.pub -e -m pem > ${ID_RSA_PUB_PEM}
}


function create_config() {
    local tgt=$1

    cat << EOF > "$tgt"
# This config file was auto generated by $0
#
# It is intended to make getting started with development easier.
# Note that the JWT_PUBLIC_KEY and private_key in the python script are a
# keypair, so updating either one will cause a problem.

JWT_ALGORITHM = "RS256"

JWT_PUBLIC_KEY = """
$(cat $ID_RSA_PUB_PEM)
"""

# To generate a token run the following command
TOKEN_GENERATION_COMMAND='''
export JWT=\$(python -c "from gateway.auth import make_token as m; private_key=\\"\\"\\"$(cat $ID_RSA)\\"\\"\\"; print(m('chain', private_key, 'RS256'))")

# once you have a token, you can run commands as
#     http 127.0.0.1:5000/sequence data=123 Authorization:"Bearer $JWT"
'''

EOF
}

target=$(make_target_path)
create_keys
create_config "$target"