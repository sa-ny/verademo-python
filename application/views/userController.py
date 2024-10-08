# userController handles user logic, including user login, registration, and profile updating.
import logging
import os
import sqlite3
import hashlib
import smtplib
import pyotp
import pickle, base64

import sqlparse
from email.mime.multipart import MIMEMultipart
from passeo import passeo
from ecdsa import SigningKey
from cryptography.hazmat.primitives.asymmetric import rsa

from django.shortcuts import redirect, render
from django.http import JsonResponse, HttpResponse
from django.db import connection, transaction, IntegrityError, DatabaseError
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.clickjacking import xframe_options_exempt
import mimetypes

from application.models import User, Blabber
from application.forms import RegisterForm


# Get logger
logger = logging.getLogger("VeraDemo:userController")
image_dir = os.path.join(os.path.dirname(__file__), '../../resources/images')

# xframe_options_exempt makes this function unprotected from clickjacking
# login checks an inputted username and password against the database, and logs them in
@xframe_options_exempt
def login(request):
    if request.method == "GET":

        target = request.GET.get('target')
        username = request.GET.get('username')

        if request.session.get('username'):
            logger.info("User is already logged in - redirecting...")
            if (target != None) and (target) and (not target == "null"):
                return redirect(target)
            else:
                return redirect('feed')

        userDetailsCookie = request.COOKIES.get('user')
        if userDetailsCookie is None or not userDetailsCookie:
            logger.info("No user cookie")
            userDetailsCookie = None
            if username is None:
                username = ''
            if target is None:
                target = ''

            # BAD CODE:
            logger.info("Entering login with username " + username + " and target " + target)
            # GOOD CODE:
            # logger.debug("Entering login.")
            
            request.username = username
            request.target = target

            return render(request, 'app/login.html',{})

        else:
            logger.info("User details were remembered")
            decoded = base64.b64decode(userDetailsCookie)
            unencodedUserDetails = pickle.loads(decoded)

            logger.info("User details were retrieved for user: " + unencodedUserDetails.username)
            
            request.session['username'] = unencodedUserDetails.username

            if (target != None) and (target) and (not target == "null"):
                return redirect(target)
            else:
                return redirect('feed')

    
    if request.method == "POST":
        logger.info("Processing login")

        username = request.POST.get('user')
        password = request.POST.get('password')
        remember = request.POST.get('remember')
        target = request.POST.get('target')

        logger.info("Attempting login with username: " + username + " and target: " + target)

        if (target != None) and (target) and (not target == "null"):
            nextView = target
            response = redirect(nextView)
        else:
            nextView = 'feed'
            response = redirect(nextView)

        try:
            logger.info("Creating the Database connection")
            with connection.cursor() as cursor:
                logger.info("Creating database query")
                # START VULN CODE
                sqlQuery = "select username, password, password_hint, created_at, last_login, \
                            real_name, blab_name from users where username='" + username + "' \
                            and password='" + hashlib.md5(password.encode('utf-8')).hexdigest() + "';"
                logger.info(sqlQuery)

                parsed = sqlparse.parse(sqlQuery)[0]
                logger.info("Attempted login with username and password: " + parsed[8].value)

                cursor.execute(sqlQuery)
                # END VULN CODE
                # GOOD CODE
                # sqlQuery = "select username, password, password_hint, created_at, last_login, \
                #            real_name, blab_name from users where username=:username and password=:password;"
                
                # logger.info(sqlQuery, {"username": username, "password": hashlib.md5(password.encode('utf-8')).hexdigest()})
                # cursor.execute(sqlQuery, {"username": username, "password": hashlib.md5(password.encode('utf-8')).hexdigest()})
                # END GOOD CODE
                row = cursor.fetchone()

                if (row):
                    columns = [col[0] for col in cursor.description]
                    row = dict(zip(columns, row))
                    logger.info("User found" + str(row)) # CWE-117
                    response.set_cookie('username', username)
                    private_key = rsa.generate_private_key(
                        public_exponent=65537, key_size=1024,) #CWE-326
                    response.set_cookie('password', private_key)

                    if (not remember is None):
                        currentUser = User(username=row["username"],
                                    password_hint=row["password_hint"], created_at=row["created_at"],
                                    last_login=row["last_login"], real_name=row["real_name"], 
                                    blab_name=row["blab_name"])
                        response = updateInResponse(currentUser, response)

                    update = "UPDATE users SET last_login=datetime('now') WHERE username='" + row['username'] + "';"
                    cursor.execute(update)

                    # if the username ends with "totp", add the TOTP login step
                    if username[-4:].lower() == "totp":
                        logger.info("User " + username + " has TOTP enabled")
                        request.session['totp_username'] = row['username']
                        response = redirect('totp')
                    else:
                        logger.info("Setting session username to " + username)
                        request.session['username'] = row['username']
                    
                else:
                    logger.info("User not found")

                    # START VULN CODE
                    request.error = "Login failed for " + username + ". Please try again."
                    # END VULN CODE
                    #SAFE:
                    #request.error = "Login failed. Please try again."
                    request.target = target

                    nextView = 'login'
                    response = render(request, 'app/' + nextView + '.html', {})
        except DatabaseError as db_err:
            logger.error("Database error", db_err)
            nextView = 'login'
            response = render(request, 'app/' + nextView + '.html', {})   
        except Exception as e:
            logger.error("Unexpected error", e)
        logger.info("Redirecting to view: " + nextView)
            
        return response

# shows the password hint on login screen
def showPasswordHint(request):
    username = request.GET.get('username')

    if (username is None or not username):
        return HttpResponse("No username provided, please type in your username first")
    
    logger.info("Entering password-hint with username: " + username)

    try:
        logger.info("Creating the Database connection")
        with connection.cursor() as cursor:
            sql = "SELECT password_hint FROM users WHERE username = '" + username + "'"
            logger.info(sql)
            cursor.execute(sql)
            row = cursor.fetchone()
            
            if (row):
                password = row[0]

                logger.info(f"Password: {password}")

                formatString = "Username '" + username + "' has password: {}"
                hint = formatString.format(password[:2] + ("*" * (len(password) - 2)))
                logger.info(hint)
                return HttpResponse(hint)
            else:
                return HttpResponse("No password found for " + username)
    except DatabaseError as db_err:
            logger.error("Database error", db_err)
            return HttpResponse("ERROR!") 
    except Exception as e:
            logger.error("Unexpected error", e)
        
    return HttpResponse("ERROR!")

@csrf_exempt
def totp(request):
    if(request.method == "GET"):
        return showTotp(request)
    elif(request.method == "POST"):
        return processTotp(request)

def showTotp(request):
    username = request.session.get('totp_username')
    logger.info("Entering showTotp for user " + username)

    # lookup the TOTP secret
    # really here to display back to the user (it's a hack for a demo app ;) )
    try:
        #Create db connection
        with connection.cursor() as cursor:

            sql = "SELECT totp_secret FROM users WHERE username = '" + username + "'"
            logger.info(sql)
            cursor.execute(sql)

            result = cursor.fetchone()
        if result:
            totpSecret = result[0]
            logger.info("Found TOTP secret")
            request.totpSecret = totpSecret
        else:
            request.totpSecret = "unknown"
    except sqlite3.IntegrityError as ie:
        logger.error(ie.sqlite_errorcode, ie.sqlite_errorname)
    except sqlite3.Error as ex :
        logger.error(ex.sqlite_errorcode, ex.sqlite_errorname)
    except Exception as e:
        logger.error("Unexpected error", e)
    

    return render(request, 'app/totp.html')


def processTotp(request):
    totpCode = request.POST.get('totpCode')
    username = request.session.get('totp_username')
    logger.info("Entering processTotp for user " + username + ", code entered: " + totpCode)

    response = redirect('login'); # assume we're going to fail

    # lookup the TOTP secret
    try:
        
        with connection.cursor() as cursor:
        
            sql = "SELECT totp_secret FROM users WHERE username = '" + username + "'"
            logger.info(sql)
            cursor.execute(sql)

            result = cursor.fetchone()
            if result:
                columns = [col[0] for col in cursor.description]
                result = dict(zip(columns, result))
                totpSecret = result["totp_secret"]
                logger.info("Found TOTP secret")

                # validate the TOTP code
                totp = pyotp.TOTP(totpSecret)

                # secret = the shared secret for the user
                # code = the code submitted by the user
                if totp.verify(totpCode):
                    logger.info("TOTP validation success")
                    request.session['username'] = username
                    nextView = redirect('feed')
                else:
                    logger.info("TOTP validation failure")
                    request.session['username'] = None
                    request.session['totp_username'] = None

                    response = redirect('login')
                    currentUser = None
                    response = updateInResponse(currentUser, response)
                    response.delete_cookie('user')
                    logger.info("Redirecting to Login...")
                    return response
            
            else:
                logger.info("Failed to find TOTP secret in database - something is very wrong")
    except sqlite3.IntegrityError as ie:
        logger.error(ie.sqlite_errorcode, ie.sqlite_errorname)
    except sqlite3.Error as ex :
        logger.error(ex.sqlite_errorcode, ex.sqlite_errorname)
    except Exception as e:
        logger.error("Unexpected error", e)

    return nextView


# funcitonality called by logout button
def logout(request):
    logger.info("Processing logout")
    request.session['username'] = None
    request.session['totp_username'] = None
    response = redirect('login')
    response.delete_cookie('user')
    logger.info("Redirecting to login...")
    return response

# csrf_exempt prevents form from requiring csrf token on submission
# transfers register request to appropriate handler
@csrf_exempt
def register(request):
    if(request.method == "GET"):
        return showRegister(request)
    elif(request.method == "POST"):
        return processRegister(request)

# renders the register.html file, called by a path in urls
def showRegister(request):
    logger.info("Entering showRegister")
    return render(request, 'app/register.html', {})

#sends username into register-finish page
def processRegister(request):
    logger.info('Entering processRegister')
    username = request.POST.get('username')
    request.username = username

    if not username:
        request.error = "No username provided, please type in your username first"
        return render(request, 'app/register.html')

    # Get the Database Connection
    logger.info("Creating the Database connection")
    try:
        with connection.cursor() as cursor:
            sqlQuery = "SELECT username FROM users WHERE username = '" + username + "'"
            cursor.execute(sqlQuery)
            row = cursor.fetchone()
            if (row):
                request.error = "Username '" + username + "' already exists!"
                return render(request, 'app/register.html')
            else:
                rand_pass = passeo().generate(10, numbers=True, symbols=True)
                sk = SigningKey.generate()
                vk = sk.verifying_key
                logger.info(type(sk))
                signature = sk.sign_digest(rand_pass.encode())
                verified = "True" if vk.verify_digest(signature, rand_pass.encode()) else "False"
                logger.info("Random password: " + rand_pass + ", Verified: " + verified)
                return render(request, 'app/register-finish.html')
            
    except sqlite3.IntegrityError as ie:
        logger.error(ie.sqlite_errorcode, ie.sqlite_errorname)
    except sqlite3.Error as ex :
        logger.error(ex.sqlite_errorcode, ex.sqlite_errorname)
    except Exception as e:
        logger.error("Unexpected error", e)
    
    return render(request, 'app/register.html')

# called by register, sends request to appropriate handling destination
@csrf_exempt
def registerFinish(request):
    if(request.method == "GET"):
        return showRegisterFinish(request)
    elif(request.method == "POST"):
        return processRegisterFinish(request)

# loads register-finish page
def showRegisterFinish(request):
    logger.info("Entering showRegisterFinish")
    return render(request, 'app/register', {})


# Interprets POST request from register form, adds user to database
def processRegisterFinish(request):
    logger.info("Entering processRegisterFinish")
    #create variables
    username = request.POST.get('username')
    cpassword = request.POST.get('cpassword')
    #fill in required username field
    form = RegisterForm(request.POST or None)
    #user now should have all the required fields

    if form.is_valid():
        password = form.cleaned_data.get('password')
        #Check if passwords from form match
        if password != cpassword:
            logger.info("Password and Confirm Password do not match")
            request.error = "The Password and Confirm Password values do not match. Please try again."
            return render(request, 'app/register.html')
        try:
            # Get the Database Connection
            logger.info("Creating the Database connection")
            with connection.cursor() as cursor:
                # START EXAMPLE VULNERABILITY 
                # Execute the query

                #set variables to make easier to use
                realName = form.cleaned_data.get('realName')
                blabName = form.cleaned_data.get('blabName')
                #mysqlCurrentDateTime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                #create query
                query = ''
                query += "insert into users (username, password, password_hint, totp_secret, created_at, real_name, blab_name) values("
                query += ("'" + username + "',")
                query += ("'" + hashlib.md5(password.encode('utf-8')).hexdigest() + "',")
                query += ("'" + password + "',")
                query += ("'" + pyotp.random_base32() + "',")
                query += ("datetime('now'),")
                query += ("'" + realName + "',")
                query += ("'" + blabName + "'")
                query += (");")
                #execute query
                cursor.execute(query)
                sqlStatement = cursor.fetchone() #<- variable for response
                logger.info(query)
                # END EXAMPLE VULNERABILITY
        except IntegrityError as ie:
            logger.error("Integrity error", ie)
            return render(request, 'app/register.html')
        except ValueError as ve:
            logger.error("Value error", ve)
            return render(request, 'app/register.html')
        except sqlite3.Error as er:
            logger.error(er.sqlite_errorcode,er.sqlite_errorname)
        except Exception as e:
            logger.error("Unexpected error", e)

        request.session['username'] = username
        emailUser(username)
        return redirect('/login?username=' + username)
    else:
        logger.info("Form is invalid")
        request.error = "Please fill out all fields"
        return render(request, 'app/register.html')
        
    # return render (request, 'app/feed.html')

# emails a user
def emailUser(username):
    try:
        message = MIMEMultipart()
        message["Subject"] = "New user registered:" + " " + username
        message["From"] = "verademo@veracode.com"
        message["To"] = "admin@example.com"
        message.set_payload("A new VeraDemo user registered: " + username)
        logger.info("Sending email to admin")

        # Using localhost and port 1025 to test emails with MailHog
        with smtplib.SMTP("localhost", 1025) as server:
            server.send_message(message)
    except smtplib.SMTPException as smtp_err:
        logger.error("SMTP error")
    except ConnectionRefusedError as conn_err:
        logger.error("Connection refused")
    except Exception as e:
        logger.error("Unexpected error")


# handles redirect for profile requests
def profile(request):
    if(request.method == "GET"):
        return showProfile(request)
    elif(request.method == "POST" and is_ajax(request)):
        return processProfile(request)
    else:
        return JsonResponse({'message':'Expected ajax request, got none'})

# populates the profile page
def showProfile(request):
    logger.info("Entering showProfile")
    username = request.session.get('username')
    if not username:
        logger.info("User is not Logged In - redirecting...")
        return redirect("/login?target=profile")
    myHecklers = None
    myInfo = None
    sqlMyHecklers = ''
    sqlMyHecklers += "SELECT users.username, users.blab_name, users.created_at " 
    sqlMyHecklers += "FROM users LEFT JOIN listeners ON users.username = listeners.listener " 
    sqlMyHecklers += "WHERE listeners.blabber='%s' AND listeners.status='Active';"
    try:
          
        logger.info("Getting Database connection")
        with connection.cursor() as cursor:    
            # Find the Blabbers that this user listens to
            logger.info(sqlMyHecklers)
            cursor.execute(sqlMyHecklers % username)
            myHecklersResults = cursor.fetchall()
            hecklers=[]
            for i in myHecklersResults:
                
                heckler = Blabber()
                heckler.setUsername(i[0])
                heckler.setBlabName(i[1])
                heckler.setCreatedDate(i[2])
                heckler.image = getProfileImageNameFromUsername(heckler.username)
                hecklers.append(heckler)
            

            # Get the audit trail for this user
            events = []

            # START EXAMPLE VULNERABILITY 
            sqlMyEvents = "select event from users_history where blabber=\"" + username + "\" ORDER BY eventid DESC; "
            logger.info(sqlMyEvents)
            cursor.execute(sqlMyEvents)
            userHistoryResult = cursor.fetchall()
            # END EXAMPLE VULNERABILITY 

            for result in userHistoryResult :
                events.append(result[0])

            # Get the users information
            sql = "SELECT username, real_name, blab_name, totp_secret FROM users WHERE username = '" + username + "'"
            logger.info(sql)
            cursor.execute(sql)
            myInfoResults = cursor.fetchone()
            if not myInfoResults:
                return JsonResponse({'message':'Error, no Inforesults found'})
            # Send these values to our View
            columns = [col[0] for col in cursor.description]
            myInfoResults = dict(zip(columns, myInfoResults))
            request.hecklers = hecklers
            request.events = events
            request.username = myInfoResults['username']
            request.image = getProfileImageNameFromUsername(myInfoResults['username'])
            request.realName = myInfoResults['real_name']
            request.blabName = myInfoResults['blab_name']
            request.totpSecret = myInfoResults['totp_secret']
    except sqlite3.Error as ex :
        logger.error(ex.sqlite_errorcode, ex.sqlite_errorname)
    except Exception as e:
        logger.error("Unexpected error", e)

        
    return render(request, 'app/profile.html', {})

'''
TODO: Test sqlite3 error handling
NOTE: This saves images to the local images folder, but it would be much easier and more secure to
store profile images in the database.
'''
# updates profile, called by jQuery and returns results without updating the active webpage
def processProfile(request):
    realName = request.POST.get('realName')
    blabName = request.POST.get('blabName')
    username = request.POST.get('username')
    file = request.FILES.get('file')
    #TODO: Experiment with safe=False on JsonResponse, send in non-dict objects for serialization
    # Initial response only get returns if everything else succeeds.
    # This must be here in order to use set_cookie later in the program
    msg = f"<script>alert('Successfully changed values!\\nusername: {username.lower()}\\nReal Name: {realName}\\nBlab Name: {blabName}');</script>"
    response = JsonResponse({'values':{"username": username.lower(), "realName": realName, "blabName": blabName}, 'message':msg},status=200)
    
    logger.info("entering processProfile")
    sessionUsername = request.session.get('username')

    # Ensure user is logged in
    if not sessionUsername:
        logger.info("User is not Logged In = redirecting...")
        response = JsonResponse({'message':"<script>alert('Error - please login');</script>"},status=403)
        #response.status_code = 403
        return response
        #TODO: Resolve request/response status and ensure same funcitonality
        
    logger.info("User is Logged In - continuing... UA=" + request.headers['User-Agent'] + " U=" + sessionUsername)
    oldUsername = sessionUsername

    # Update user information

    try:
        logger.info("Getting Database connection")
        # Get the Database Connection
        # TODO: Error in SQL execution
        with connection.cursor() as cursor:
            logger.info("Preparing the update Prepared Statement")
            update = "UPDATE users SET real_name='%s', blab_name='%s' WHERE username='%s';"
            logger.info("Executing the update Prepared Statement")
            cursor.execute(update % (realName,blabName,sessionUsername))
            updateResult = cursor.fetchone()

            # If there is a record...
            if updateResult:
                # failure
                
                response = JsonResponse({'message':"<script>alert('An error occurred, please try again.');</script>"},status=500)
                #response.status_code = 500
                return response
    except sqlite3.IntegrityError as e:
        logger.error(e.sqlite_errorcode, e.sqlite_errorname)
        response = JsonResponse({'message':"<script>alert('An Database error occurred, please try again.');</script>"},status=500)
        #response.status_code = 500
        return response
    except sqlite3.Error as ex :
        logger.error(ex.sqlite_errorcode, ex.sqlite_errorname)
    except Exception as e:
        logger.error("Unexpected error", e)
        response = JsonResponse({'message':"<script>alert('An error occurred, please try again.');</script>"},status=500)
        #response.status_code = 500
        return response

    # Rename profile image if username changes
    if username != oldUsername :
        
        if usernameExists(username):
            
            response = JsonResponse({'message':"<script>alert('That username already exists. Please try another.');</script>"},status=409)
            #response.status_code = 409
            return response

        if not updateUsername(oldUsername, username):
            
            response = JsonResponse({'message':"<script>alert('An error occurred, please try again.');</script>"},status=500)
            #response.status_code = 500
            return response
        
        # Update all session and cookie logic
        request.session['username'] = username
        response.set_cookie('username',username)
        

        # Update remember me functionality
        userDetailsCookie = request.COOKIES.get('user')
        if userDetailsCookie is not None:
            decoded = base64.b64decode(userDetailsCookie)
            unencodedUserDetails = pickle.loads(decoded)
            # unencodedUserDetails = pickle.loads(base64.b64decode(userDetailsCookie))
            unencodedUserDetails.username = username
            response = updateInResponse(unencodedUserDetails, response)
        

        # Update user profile image
    if file:
        imageDir = image_dir
        # imageDir = os.path.realpath("./resources/images/")
        

        # Get old image name, if any, to delete
        oldImage = getProfileImageNameFromUsername(username)
        if oldImage:
            os.remove(os.path.join(imageDir,oldImage))
        
        try:
            #Potential VULN? ending with .png, having different file type
            extension = file.name.lower().endswith('.png')
            if extension:
                path = imageDir + '/' + username + '.png'
            else:
                
                response = JsonResponse({'message':"<script>alert('File must end in .png');</script>"},status=422)
                return response
            logger.info("Saving new profile image: " + path)

            with open(path, 'wb') as destination:
                for chunk in file.chunks():
                    destination.write(chunk)
        except IOError as e:
            logger.error("Error occured saving image", e)
            response = JsonResponse({'message':"<script>alert('An error occurred, please try again.');</script>"},status=500)
            #response.status_code = 500
            return response
        
        except Exception as ex :
            logger.error(ex)
    
    return response

# updates the user cookies
def updateInResponse(user, response):
    # encoded = base64.b64encode(user)
    # cookie = pickle.dumps(encoded.decode())
    pickled = pickle.dumps(user)
    cookie = base64.b64encode(pickled).decode('ASCII')
    response.set_cookie('user', cookie)
    return response

# logic to download uploaded profile image
def downloadImage(request):
    imageName = request.GET.get('image')
    logger.info("Entering downloadImage")

    username = request.session.get('username')
    if not username:
        logger.info("User is not Logged In - redirecting...")
        return redirect('/login?target=profile')
    logger.info("User is Logged In - continuing... UA=" + request.headers["User-Agent"] + " U=" + username)

    f = image_dir
    path = f + "/" + imageName

    logger.info("Fetching profile image: " + path)

    try:
        if os.path.exists(path):
            with open(path, 'rb') as file:
                mime_type = mimetypes.guess_type(path)[0]
                if mime_type is None:
                    mime_type = "application/octet-stream"
                logger.info("MIME type: " + mime_type)
                response = HttpResponse(file.read(), content_type=mime_type)
                response.headers['Content-Disposition'] = 'attachment; filename=' + imageName
                return response
    except ValueError as ve:
            logger.error("Security Error", ve)
            return render(request, "app/profile.html", {"error" : ve})
    except FileNotFoundError as fnfe:
            logger.error("File Error", fnfe)
            return render(request, "app/profile.html", {"error" : fnfe})
    except Exception as e:
            logger.error("Unexpected error", e)
            return render(request, "app/profile.html", {"error" : e})


    return render(request, "app/profile.html", {})

# Check if a username is already in database
def usernameExists(username):
    username = username.lower()
    # Check is the username already exists
    try:
        # Get the Database Connection
        logger.info("Getting Database connection")
        with connection.cursor() as cursor:
            logger.info("Preparing the duplicate username check Prepared Statement")
            sqlStatement = "SELECT username FROM users WHERE username='%s'"
            cursor.execute(sqlStatement % (username,))
            result = cursor.fetchone()
            if not result:
                # username does not exist
                return False
            
    except sqlite3.Error as er:
        logger.error(er.sqlite_errorcode,er.sqlite_errorname)
    except ModuleNotFoundError as ex:
        logger.error(ex)
    except Exception as e:
        logger.error("Unexpected error", e)

    logger.info("Username: " + username + " already exists. Try again.")
    return True

# updates a username and all it's dependants to a new username
def updateUsername(oldUsername, newUsername):
    # Enforce all lowercase usernames
    oldUsername = oldUsername.lower()
    newUsername = newUsername.lower()

    # Check is the username already exists
    try:
        logger.info("Getting Database connection")
        # Get the Database Connection
        with transaction.atomic():
            with connection.cursor() as cursor:

                # Update all references to this user
                sqlStrQueries = [
                    "UPDATE users SET username='%s' WHERE username='%s'",
                    "UPDATE blabs SET blabber='%s' WHERE blabber='%s'",
                    "UPDATE comments SET blabber='%s' WHERE blabber='%s'",
                    "UPDATE listeners SET blabber='%s' WHERE blabber='%s'",
                    "UPDATE listeners SET listener='%s' WHERE listener='%s'",
                    "UPDATE users_history SET blabber='%s' WHERE blabber='%s'" ]
        
                # Execute updates as part of a batch transaction
                # This will roll back all changes if one query fails
                for query in sqlStrQueries:
                    cursor.execute(query % (newUsername,oldUsername))


        # Rename the user profile image to match new username
        oldImage = getProfileImageNameFromUsername(oldUsername)
        if oldImage:
            extension = '.png'

            logger.info("Renaming profile image from " + oldImage + " to " + newUsername + extension)
            path = image_dir
            # path = os.path.realpath("./resources/images")
            oldPath = path + '/' + oldImage
            newPath = path + '/' + newUsername + extension
            os.rename(oldPath, newPath)
        return True
    except (sqlite3.Error, ModuleNotFoundError) as ex:
        logger.error(ex)
    except IntegrityError as er:
        logger.error(er)
    except Exception as e:
        logger.error("Unexpected error", e)

    # Error occurred
    return False


# Takes a username and searches for the profile image for that user
def getProfileImageNameFromUsername(username):
    f = image_dir
    # f = os.path.realpath("./resources/images")
    matchingFiles = [file for file in os.listdir(f) if file.startswith(username + ".")]

    if not matchingFiles:
        return None
    return matchingFiles[0]

# checks if a request was made using a JQuery ajax request
def is_ajax(request):
    return request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'
