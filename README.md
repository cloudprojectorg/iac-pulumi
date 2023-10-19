# Assignment README

## Prerequisites
Before you can build and deploy this web application locally, you'll need to ensure that you have the following prerequisites installed:

- [Node.js](https://nodejs.org/)
- [MySQL](https://www.mysql.com/)
- [Git](https://git-scm.com/)

## API Documentation
For detailed information on the API endpoints, request/response formats, and usage examples, please refer to the [API Documentation]([https://link-to-api-documentation](https://app.swaggerhub.com/apis-docs/csye6225-webapp/cloud-native-webapp/fall2023-a3)).

You can find comprehensive documentation on how to interact with the API and perform various actions.

## Build and Deploy Instructions

### 1. Clone the Repository
Clone the repository to your local machine:
### 2. Install Dependencies
Navigate to the project directory and install the required Node.js dependencies:
    cd your-repo
    npm install
### 3. Setup MySQL Database
Make sure you have a MySQL database set up and running. Configure the database connection in the project's configuration file, if necessary.
### 4. Bootstrapping Database
The application is designed to automatically bootstrap the database at startup. It will create the necessary schema, tables, indexes, and more based on your configuration.
### 5. Load User Accounts
Load user account information from a CSV file located at /opt/user.csv. The application will create user accounts based on the data provided in the CSV file. If an account already exists, it will not be updated
### 6. Hash User Passwords
User passwords will be hashed using BCrypt before being stored in the database. Security is a top priority
### 7. Run the Application
Start the Node.js application:
    npm start

### 8. Authentication
To make API calls to authenticated endpoints, you must provide a basic authentication token. The web application supports Token-Based authentication

## Technologies Used
1. Node.js
2. Sequelize (ORM for Node.js)
3. MySQL
4. Mocha and Chai for integration tests

## Additional Notes
Deletion of user accounts is not supported.
Users cannot set values for account_created and account_updated fields; any provided values for these fields are ignored.

test
