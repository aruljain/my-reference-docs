import {
  SecretsManagerClient,
  GetSecretValueCommand,
} from "@aws-sdk/client-secrets-manager";
const client = new SecretsManagerClient({ region: "us-east-1" });
let globalCache = "";
export const handler = async (event) => {
  const secretKey = "Client1";
  const secretName = "dev/secret/apiconnect";
  let secretValue = "";
  if (globalCache == undefined || globalCache == null) {
    console.log("Fetched directly from secret manager!!!");
    globalCache = await getSecret(secretName);
    const completeSecretJson = JSON.parse(globalCache);
    secretValue = JSON.parse(completeSecretJson[secretKey]);
    return secretValue;
  }
};
const getSecret = async (secretName, region) => {
  try {
    console.log("Fetching secret value ");
    const command = new GetSecretValueCommand({ SecretId: secretName });
    const secretValue = await client.send(command);
    if ("SecretString" in secretValue) {
      console.log("SecretString found in secretValue");
      return secretValue.SecretString;
    } else {
      console.log("ascii conversion of secret value : ");
      let buff = new Buffer(secretValue.SecretBinary, "base64");
      return buff.toString("ascii");
    }
  } catch (err) {
    console.log("SecretsManager => err:", err);
    if (err.code === "Decryption FailureException") {
      console.log("SecretsManager => err ", err);
      if (err.code === "DecryptionFailureException") {
        // Secrets Manager can't decrypt the protected secret text using the provided KMS key. // Deal with the exception here, and/or rethrow at your discretion. console.log("SecretsManager => Decryption FailureException ", err);
        throw err;
      } else if (err.code === "InternalServiceErrorException") {
        // An error occurred on the server side.
        // Deal with the exception here, and/or rethrow at your discretion. console.log("SecretsManager => InternalServiceErrorException ", err);
        throw err;
      } else if (err.code === "InvalidParameter Exception") {
        // You provided an invalid value for a parameter.
        // Deal with the exception here, and/or rethrow at your discretion. console.log("SecretsManager => InvalidParameterException
        throw err;
      } else if (err.code === "InvalidRequestException")
        // You provided a parameter value that is not valid for the current state of the resource. // Deal with the exception here, and/or rethrow at your discretion.
        console.log("SecretsManager => InvalidRequestException ", err);
      throw err;
    } else if (err.code === "ResourceNotFoundException") {
      // We can't find the resource that you asked for.
      // Deal with the exception here, and/or rethrow at your discretion. console.log("SecretsManager => ResourceNotFoundException', err);
      console.log("SecretsManager => ResourceNotFoundException ", err);
      throw err;
    }
  }
};