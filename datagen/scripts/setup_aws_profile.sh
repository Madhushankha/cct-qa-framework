#!/bin/bash
# Setup AWS SSO profile for AC-CCT-CRT environment
# Run this script once to configure the profile

set -e

PROFILE_NAME="ac-cct-crt"
SSO_START_URL="https://d-9067181781.awsapps.com/start"
SSO_REGION="us-east-1"
ACCOUNT_ID="050752605169"
ROLE_NAME="CCE-Developer"
OUTPUT_FORMAT="json"

echo "Setting up AWS SSO profile: $PROFILE_NAME"
echo ""

# Check if profile already exists
if aws configure list-profiles 2>/dev/null | grep -q "^${PROFILE_NAME}$"; then
    echo "Profile '$PROFILE_NAME' already exists."
    read -p "Do you want to reconfigure it? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Skipping profile configuration."
        exit 0
    fi
fi

echo "Configuring AWS SSO profile..."
echo ""
echo "NOTE: You may need to update the SSO_START_URL if it differs from:"
echo "  $SSO_START_URL"
echo ""

# Configure the SSO profile
aws configure set sso_start_url "$SSO_START_URL" --profile "$PROFILE_NAME"
aws configure set sso_region "$SSO_REGION" --profile "$PROFILE_NAME"
aws configure set sso_account_id "$ACCOUNT_ID" --profile "$PROFILE_NAME"
aws configure set sso_role_name "$ROLE_NAME" --profile "$PROFILE_NAME"
aws configure set region "$SSO_REGION" --profile "$PROFILE_NAME"
aws configure set output "$OUTPUT_FORMAT" --profile "$PROFILE_NAME"

echo ""
echo "Profile '$PROFILE_NAME' configured successfully!"
echo ""
echo "To login, run:"
echo "  aws sso login --profile $PROFILE_NAME"
echo ""
echo "To verify, run:"
echo "  aws s3 ls --profile $PROFILE_NAME"
echo ""
