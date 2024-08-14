### Import required modules
import base64
from os.path import isfile, join, basename, dirname, getsize, abspath
from os import makedirs
import xml.etree.ElementTree as ET
from hashlib import sha256, sha1
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA1
from binascii import unhexlify
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
import scripts.filetype as filetype
from itertools import permutations
from pathlib import Path
import json
import datetime

### Import ALEAPP Modules
from scripts.artifact_report import ArtifactHtmlReport
from scripts.ilapfuncs import logfunc, tsv, timeline, is_platform_windows, media_to_html

### Function to reduce code (slightly) to be used with log function
def printFunc(dataToPrint,prependDash,newLine, appendDash):
    stringToPrint = ''
    if prependDash:
        stringToPrint += ('\n------------------------------------------\n')
    stringToPrint += dataToPrint
    if appendDash:
        stringToPrint += ('\n------------------------------------------')
    if newLine:
        stringToPrint += '\n'    
    logfunc(stringToPrint)

### Identify master encryption key
def identifyMasterKey(PIN,masterIV):
    ### PBKDF2 key derivation
    derivedKey = PBKDF2(unhexlify(PIN),  masterIV, 16, count=100, hmac_hash_module=SHA1).hex()
    ### Create new instace of cipher using masterIV and derivedKey
    cipher = AES.new(bytes.fromhex(derivedKey), AES.MODE_CBC, masterIV)
    ### Decrypt the first encrypted value
    masterKey = firstDecryptedValue = cipher.decrypt(interpretKeyFile.firstEncryptedValue)
    ### Decrypt the second encrypted value
    masterKey = cipher.decrypt(interpretKeyFile.secondEncryptedValue)
    return(masterKey,derivedKey, firstDecryptedValue)

### Read relevant files from keyFile
def interpretKeyFile(_keyFile):
    with open(_keyFile, 'rb') as keyFile:
        keyFile = keyFile.read()
        interpretKeyFile.masterIV = keyFile[8:24]
        interpretKeyFile.firstEncryptedValue = keyFile[24:56]
        interpretKeyFile.secondEncryptedValue = keyFile[56:]    

### Decryption function
def decryptData(encryptedInput, masterKey):
    if(int.from_bytes(encryptedInput[:4], "big") == 16):
        base = 0
    else:
        base = 4     
    ### Get the IV from the file
    fileIV = encryptedInput[base + 4: base + 20 ]
    ### Get the encrypted data length
    fileSize = int.from_bytes(encryptedInput[base + 20: base + 24], "big")
    ### Create new instance of cipher using IV from the file and master key.
    cipher = AES.new(masterKey, AES.MODE_CBC, fileIV)
    ### Decrypt the data
    decryptedData = unpad(cipher.decrypt(encryptedInput[-fileSize:]),16)
    ### Return the decrypted value
    return(decryptedData)        

### Main
def get_AVG(files_found, report_folder, seeker, wrap_text, time_offset):
    
    ### Known variables to be used
    pinDict = {}
    PinSettingsExists = False
    keyFileFound = False
    fileList = []
    metaDataFile = ''
    encryption_details_data_list = []
    media_data_list = []

    ### Base64 encoded data containing the converted PINs
    pinFile = '''
    '''
    ### Splitting the data into lines
    decodeBase64 = base64.b64decode(pinFile).split(b'\n')

    ### Variables used for iterating through list
    i = 0
    ii = 1

    ### While the variable 'ii' is less than the list length
    while ii < len(decodeBase64):
        ## Add entries to dictionary for use later
        pinDict[decodeBase64[i]] = decodeBase64[ii]
        ## Increment values by 2 each time for the next pair
        i +=2
        ii +=2
    
    ### Iterate through files found
    for file_found in files_found:
        file_found = str(file_found)

        ### If it's not a file, skip it
        if not isfile(file_found):
            continue
        
        ### Checking for key store file 
        if(dirname(file_found).endswith('.key_store')):
            ### Decryption is possible
            keyFileFound = True
            keyStore = file_found
        
        ### Checking for PIN settings file (shared_prefs)
        if(file_found.endswith('PinSettingsImpl.xml')):
            ### Set boolean to true
            PinSettingsExists = True
            pinSettingsFile = file_found

        ### Checking for metadata file
        if(dirname(file_found).endswith('.metadata_store')):
            metaDataFile = file_found
        
        ### Check for all other media files and add them to a list for decrypting later
        if((dirname(file_found).endswith('.mid_pictures')) or
        (dirname(file_found).endswith('.thumbnail')) or
        (dirname(file_found).endswith('pictures'))):
            fileList.append(file_found)   

    ### Check if key file found
    if keyFileFound:
        ### Report generation section
        printFunc('Key file exists:\tDecryption Possible', True, False, True)
        printFunc('Reading relevant values for decryption', True, False, True)
        ### Open the '.key_store' file and obtain relevant values
        interpretKeyFile(keyStore)
        encryption_details_data_list.append(('Master IV',interpretKeyFile.masterIV.hex()))
        encryption_details_data_list.append(('First Encrypted Value',interpretKeyFile.firstEncryptedValue.hex()))
        encryption_details_data_list.append(('Second Encrypted Value',interpretKeyFile.secondEncryptedValue.hex()))

    ### If not, exit as decryption not possible (but will still check to see if settings file with PIN exists)
    ### This can be the case if a PIN is setup for any of the other parts of the application such as app lock
    else:
        printFunc('Key file not found, no decryption possible.', True, False, True)

    ### If the file exists then just pull the SHA1 and brute force
    if PinSettingsExists:
        ### Print the file has been found
        printFunc(f'Found settings file\t{pinSettingsFile}', True, False, True)
        ### Traverse the XML file
        tree = ET.parse(pinSettingsFile)
        ### Set the root of the XML file
        root = tree.getroot()
        ### Will always be PIN, identify and assign to variable
        userPIN = root.findall('./string[@name="encrypted_pin"]')[0].text
        ### Print the hash
        encryption_details_data_list.append(('User PIN Hash' ,userPIN))
        printFunc('Will attempt brute force of PIN...', True, False, True)
        
        ### Bruteforce PIN
        ### Range 0000 - 9999
        for i in range(0,10000):
            currentPIN = ('{0:04}'.format(i)).encode('utf-8')
            ## Section of code to try the hash process and assign PasscodFound if correct
            ## Compare the current PIN SHA1 and the provided AVG PIN
            if sha1(currentPIN).hexdigest() == userPIN:
                encryption_details_data_list.append(('User PIN' ,currentPIN.decode("utf-8")))
                break
            else:
                continue

        ### If it exists assign to variable
        try:
            if userPattern := root.findall('./string[@name="encrypted_pattern"]')[0].text:
                ### If pattern present will need to be bruteforced
                encryption_details_data_list.append(('User Pattern Hash' ,userPattern))
                printFunc('Will attempt brute force of Pattern... ', True, False, True)
                for patternLength in range(4,10):
                    currentPermutation = permutations(range(0,9),patternLength)     
                    for x in currentPermutation:
                        currentPattern = ''.join(str(v) for v in x)
                        currentPatternHex = (unhexlify(''.join([f'0{x}' for x in currentPattern])))
                        if sha1(currentPatternHex).hexdigest() == userPattern:
                            encryption_details_data_list.append(('User Pattern' ,currentPattern))
                            break   
        ### If it doesn't log it
        except IndexError:
            printFunc(f'*****\t\t\tNo user Pattern found in file', True, False, True) 

        ### If the keyfile is present continue with the decryption using the identified PIN        
        if keyFileFound:         
            javaPIN = pinDict[currentPIN]
            encryption_details_data_list.append(('Java Equivilant',javaPIN.decode("utf-8")))
            printFunc(f'*****\t\t\tDeriving PBKDF2 key', True, False, True)
            ### derivedKey derivation 
            ## Derive the Primary key from the provided PIN
            keyData = identifyMasterKey(javaPIN, interpretKeyFile.masterIV)
            masterKey = keyData[0]
            derivedKey = keyData[1]
            encryption_details_data_list.append(('Derived Key',derivedKey))
            encryption_details_data_list.append(('Master Key',masterKey.hex()))
        ### Otherwise there is nothing else that can be done
        else:
            printFunc('Key file not found, no decryption possible, exiting...', False, False, False)
    else:
        ### If the file doesn't exist the PIN will require bruteforce against the key file.
        printFunc('*****\t\t\tCould not find settings file, will require bruteforce', False, False, True)
        printFunc('*****\t\t\tBruteforce requied and will take some time', True, False, True)
        ### For each PIN in the dictionary
        for pin in pinDict:
        ### Assign masterKey based on current PIN   
            keyData = identifyMasterKey(pinDict[pin], interpretKeyFile.masterIV)
            masterKey = keyData[0]
            derivedKey = keyData[1]
            firstDecryptedValue =  keyData[2]
            ### New sha256 instance
            masterKeyHash = sha256()
            ### Hash the final decrypted output
            masterKeyHash.update(masterKey)
            ### Check whether the decrypted data mataches the expected string
            if masterKeyHash.hexdigest() == firstDecryptedValue.hex():
                encryption_details_data_list.append(('User PIN' ,pin.decode("utf-8")))
                encryption_details_data_list.append(('Derived Key',derivedKey))
                break      

    if encryption_details_data_list:
        report = ArtifactHtmlReport("AVG - Encryption Details")
        report.start_artifact_report(report_folder, "AVG - Encryption Details")
        report.add_script()
        data_headers = ("Encryption Details", "Value",) # Don't remove the comma, that is required to make this a tuple as there is only 1 element
        report.write_artifact_data_table(data_headers, encryption_details_data_list, "Multiple Files")
        report.end_artifact_report()
        tsvname = f"AVG - Encryption Details"
        tsv(report_folder, data_headers, encryption_details_data_list, tsvname, "Multiple Files")
  
    ### Media file decryption   
    ## '.metadata_store' to be dealt with differently
    ### If '.metadata_store' exists, decrypt the file and iterate through the contents and write to report
    if(metaDataFile):
         metaDataDict = {}
         with open (metaDataFile, 'rb') as currentFile:
            ### Decrypt the data
            decryptedData = decryptData(currentFile.read(), masterKey)
            decryptedMetaDataFile = json.loads(decryptedData.decode('utf-8'))
            ### Reading the files from the metadata file
            ### Not all entries will be used later
            for entries in decryptedMetaDataFile['items']:
                metaDataDict[entries["vaultFileName"]] = {}
                metaDataDict[entries["vaultFileName"]]["Original File Path"] = (entries["originFilePath"])
                metaDataDict[entries["vaultFileName"]]["File Width"] = (entries["width"])
                metaDataDict[entries["vaultFileName"]]["File Height"] = (entries["height"])
                metaDataDict[entries["vaultFileName"]]["Encrypted Date"] = (entries["date"])
                metaDataDict[entries["vaultFileName"]]["File Size"] = (entries["size"])
                
    ### If media file listing not empty
    ## Go through list and decrypt each file
    ## Files will be identifiable by 'mid', 'thumb' and full name for full picture    
    if fileList:
        ### Create the directory for the files to be written to
        makedirs(join(report_folder, "AVGDecryptedFiles"))
        ### Create report for media files
        media_report = ArtifactHtmlReport('AVG - Media Files')
        media_report.start_artifact_report(report_folder, 'AVG - Media Files')
        media_report.add_script()
        media_data_headers = ('Media', 'Decrypted Filename', 'Original File Path', 'Encrypted Date', 'File Size' , 'Decrypted Full Path')
        tolink = []
        for files in fileList:
            ### Open file to be decrypted
            with open (files, 'rb') as currentFile:
                ### Decrypt the data
                decryptedData = decryptData(currentFile.read(), masterKey)
                ### Looping to see how to prepend the files (as there should be 3 for each)
                if(dirname(files).endswith('.thumbnail')):
                    append = '_thumb'
                elif(dirname(files).endswith('.mid_pictures')):
                    append = '_mid'
                elif(dirname(files).endswith('pictures')):        
                    append = ''
                ### Guess the correct file extension
                fileExtension = filetype.guess(decryptedData)
                if not fileExtension:
                    fileExt = 'unknown'
                else:
                    fileExt = (append + '.' + fileExtension.extension)
                exportFileName =  (basename(files)  + fileExt)
                destinationFile = join(report_folder, "AVGDecryptedFiles", exportFileName)
                ### Create the decrypted file
                with open (destinationFile, 'wb') as decryptedFile:
                    decryptedFile.write(decryptedData)
                    decryptedFile.close()
                ### Close the working file
                currentFile.close()  
                
                ### Add media files witin the report
                ### If it is the main file, include it in the report
                if append == '':
                    if basename(files) in metaDataDict:
                        origFilePath = metaDataDict[basename(files)]["Original File Path"]
                        encryptedDate = datetime.datetime.utcfromtimestamp(int(metaDataDict[basename(files)]["Encrypted Date"]) / 1000)
                        fileSize = metaDataDict[basename(files)]["File Size"]
                    else:
                        origFilePath, encryptedDate, fileSize = "No Data"
                    tolink.append(destinationFile)
                    thumb = media_to_html(destinationFile, tolink, join(report_folder,"AVGDecryptedFiles"))
                    media_data_list.append((thumb, exportFileName, origFilePath, encryptedDate, fileSize,files))
                ### If it is a thumb etc do not include in report
                else:
                    pass    
        
        ### Write report
        maindirectory = str(Path(files).parents[1])
        media_report.write_artifact_data_table(media_data_headers, media_data_list, maindirectory, html_no_escape=['Media'])
        report.end_artifact_report()
            
        tsvname = f'AVG - Media Files'
        tsv(report_folder, data_headers, media_data_list, tsvname)                  
    else:
        logfunc('No files found to decrypt')
        
__artifacts__ = {
        "AVG": (
                "Encrypting Media Apps",
                ('*/com.antivirus/shared_prefs/PinSettingsImpl.xml', '*/Vault/*'),
                get_AVG)
}