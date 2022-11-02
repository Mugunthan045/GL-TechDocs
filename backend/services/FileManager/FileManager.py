# Libraries
# from asyncore import file_dispatcher
import os
import warnings
import logging
import yaml
import requests
from flask import request,make_response
import json
import re
#from functools import singledispatchmethod
from datetime import datetime
from xml.dom.xmlbuilder import DocumentLS 
import sqlalchemy as db
from sqlalchemy import create_engine, select, update
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from DBConnect import session_factory
from orm_Tables import Document, Permission, DocumentHistory, UserHistory
from flask import Flask, render_template, url_for, redirect, session, flash, request, jsonify, json
from flask import Blueprint
from flask import current_app
#from Users import User
from ..UserAuthentication.JWTAuthentication import authentication
from ..DocumentVersionManager.DocumentVersionManager import VersionManage
from ..UserHistoryManager import *
from ..Permissions.permissions import get_user_permissions


# Suppress warnings
warnings.filterwarnings("ignore")

fileManagerBlueprint = Blueprint('fileManagerBlueprint', __name__)

@fileManagerBlueprint.before_request
def before_request_func():

    data_path = current_app.config["DIR_ROOT"] + current_app.config["DIR_DATA"] 
    log_path = current_app.config['DIR_ROOT'] + current_app.config['DIR_LOG']
    logging.basicConfig(filename=log_path)

####################
# File Manager Class
class FileManage:
    v_filename = ''
    v_filepath = ''
    v_version  = 0
        
    @classmethod
    def createNewFile(cls, userid, filename, doctext):
        datestr  = datetime.today().strftime('%Y%m%d%H%M%S')
        dirpath  = data_path + '/' + userid
        if (filename == ""):
            filename = 'untitled_'+datestr+'.tex'
        filepath = dirpath+'/'+filename
        if not os.path.exists(dirpath):
            os.makedirs(dirpath)
        cls.v_filename = filename
        cls.v_filepath = filepath
        
    
    @classmethod
    def writeToFile(cls, filepath, text):
        file_obj = open(filepath, "w")
        file_obj.write(text)
        file_obj.close()
        
    @classmethod
    def createNewVersion(cls, CurrVer):
        cls.v_version = CurrVer + 1
    
    @classmethod
    def uploadFile(cls, userid, filename, docdata):
        datestr  = datetime.today().strftime('%Y%m%d%H%M%S')
        dirpath  = data_path + '/' + userid
        filepath = dirpath+'/'+filename
        if not os.path.exists(dirpath):
            os.makedirs(dirpath)
        file_obj = open(filepath, "w")
        file_obj.write(docdata)
        file_obj.close() 

        cls.v_filename = filename
        cls.v_filepath = filepath
        
'''
# API to create a new file either empty or with data given
# Input: {'DocId':'', 'DocName':'', 'DocText':'', 'Uploaded':'', 'RefDocId':''}
# Processing: 
# 1. Authenticate user
# 2. Extract all input data 
# 3. Create file on the folder path
# 4. If data given, write the data to the file
# 5. Create an entry into Documents & Permissions table
# 6. Output: UserId, DocId, DocName, FilePath 
'''
@fileManagerBlueprint.route('/api/filecreate', methods = ['GET', 'POST'])
@authentication
def file_Create(user_id):
    userid      = 0
    docid       = 0
    docname     = ''
    doctext     = ''
    ver         = 0
    newfilepath = ''
    refdocid    = 0
    reffilepath = ''
    data_out    = ''
    mess_out    = ''

    current_app.logger.info("Service File Create initiated")

    if(request.method == 'POST'):
        # request data
        content  = request.get_json(silent=True)
        userid   = user_id
        docid    = content['DocId']
        docname  = content['DocName']
        doctext  = content['DocText']
        isupload = content['IsUpload']
        refdocid = content['RefDocId']
        
        session  = session_factory()
        file_obj = FileManage()
        ver_obj  = VersionManage()
    
        # Save data into database
        try:
            # new file
            if ((docid == 0) or (docid == '')):
                ver = 1
            else:
                # return jsonify({"message":"Wrong service called. Create file is for new file only!"})
                raise Exception("Wrong service called. Create file is for new file only!")
            
            # Method to create a new file path - object will store the values of filename, file path
            ver_obj.createNewVersionFile(userid, docname, ver, '')
            newfilepath = ver_obj.v_file_path
            docname     = ver_obj.v_file_name
        
            # create the file
            open(newfilepath, 'a').close()
        
            # entry into Documents table
            doc_entry = Document(userid, docname, newfilepath, datetime.today(), ver, isupload)
            session.add(doc_entry)
            session.flush()
            docid_out = doc_entry.DocId
            session.commit()
            # entry into permissions table
            perm_entry = Permission(docid_out, userid, 'W')
            session.add(perm_entry)
            session.flush()
            session.commit()
            # entry into DocumentHistory table
            dochist_entry = DocumentHistory(userid, docid_out, datetime.today(), docname, newfilepath, ver)
            session.add(dochist_entry)
            session.flush()
            session.commit()
            # entry into UserHistory table
            userhist_entry = UserHistory(userid, docid_out, datetime.today(), docname, 'Create')
            session.add(userhist_entry)
            session.flush()
            session.commit()
            
            # if there is a reference document given, copy the contents to the new file
            if (refdocid != 0):
                sql_stmt = select(Document.FilePath).where(Document.DocId == refdocid)
                sql_result = session.execute(sql_stmt)
                # there is always only 1 row
                for row in sql_result:
                    reffilepath = row.FilePath
                
                with open(reffilepath, 'r') as firstfile, open(newfilepath, 'a') as secondfile:
                    for line in firstfile:
                        secondfile.write(line)
            # Write data if given from the user
            elif (doctext != ''):
                file_obj.writeToFile(newfilepath, doctext)
            
            session.close()
            # building output data
            data_out = json.dumps({'UserId':userid, 'DocId':docid_out, 'DocName':docname, 'Filepath': newfilepath})
            mess_out = 'Success'
        except Exception as err:
            mess_out = "Error"
            current_app.logger.exception("Failure Creating File! "+str(err))
    
    current_app.logger.info("Service File Create ended")
    # return the message and data string as response
    return jsonify(message=mess_out, data=data_out)

'''
# API to modify a file
## This can be to update a file or save the file
# Input: {'DocId':'', 'DocName':'', 'DocText':''}
# Processing: 
# 1. Authenticate user
# 2. Extract all input data 
# 3. Process the request - update the document or save the document
# 3.a Update the current document - expect DocId to be sent
# 3.b Save the current document - expect DocId to be sent
# - we create a new file every time this request is sent to keep history of things
# 4. Output: UserId, DocId, DocName, FilePath
'''
@fileManagerBlueprint.route('/api/filemodify', methods = ['GET', 'POST'])
@authentication
def file_Modify(user_id):
    current_app.logger.info("Service File Modify initiated")
    data_out = ''
    mess_out = ''

    if(request.method == 'POST'):
        # retrieve data inputs from the request
        content     = request.get_json(silent=True)
        userid      = user_id
        docid       = content['DocId']
        docname     = content['DocName']
        doctext     = content['DocText']
        sql_stmt    = ''
        newfilepath = ''
        ver         = 0
        
        # open db connection
        session  = session_factory()
        file_obj = FileManage()
        ver_obj  = VersionManage()
        
        try:
            if ((docid == 0) or (docid == '')):
                raise Exception('Document reference id not given. Cannot process!')
                    
            # check if the document exists
            sql_stmt = select(Document.DocId).where(Document.DocId == docid)
            sql_result = session.execute(sql_stmt)
            noofrecords = len(sql_result.all())
            
            # DocId not found so create a new file & save - mostly save operation
            if (noofrecords == 0):
                ver = 1
                ver_obj.createNewVersionFile(userid, docname, ver, '')
                newfilepath = ver_obj.v_file_path
                docname     = ver_obj.v_file_name
                
                # entry into Documents table
                doc_entry = Document(userid, docname, newfilepath, datetime.today(), ver, 'N')
                session.add(doc_entry)
                session.flush()
                docid = doc_entry.DocId
                session.commit()
            # Continue either updating or saving the file
            else:
                userperm = get_user_permissions(userid, docid) #W/R
                # User has write permission
                if 'W' in userperm:
                    # get and create a new version for the document
                    sql_stmt = (select(Document.Version).where(Document.DocId == docid))
                    sql_result = session.execute(sql_stmt)
                    # there is always only 1 row
                    for row in sql_result:
                        ver_row = row[0]
                        file_obj.createNewVersion(ver_row)
                        ver = file_obj.v_version
                    # create a new file with new version
                    ver_obj.createNewVersionFile(userid, docname, ver, '')
                    newfilepath = ver_obj.v_file_path
                    docname     = ver_obj.v_file_name
                    
                    # UPDATES
                    mod_date = datetime.today()
                    # update Documents table with the latest version
                    sql_stmt = update(Document)\
                        .where(Document.DocId == docid)\
                        .values({Document.FilePath:newfilepath, Document.Version:ver, Document.ModifiedDate:mod_date, Document.ModifiedBy:userid})
                    session.execute(sql_stmt)
                    session.commit()
                else:
                    raise Exception("User does not have access to modify!")
            
            # update the content to this file
            file_obj.writeToFile(newfilepath, doctext)
            # insert new entry into the Document History table
            dochist_entry = DocumentHistory(userid, docid, datetime.today(), docname, newfilepath, ver)
            session.add(dochist_entry)
            session.flush()
            session.commit()
            # entry into UserHistory table
            userhist_entry = UserHistory(userid, docid, datetime.today(), docname, 'edit')
            session.add(userhist_entry)
            session.flush()
            session.commit()
            
            session.close()

            # building output data
            data_out = json.dumps({'UserId':userid, 'DocId':docid, 'DocName':docname, 'Filepath': newfilepath})
            mess_out = 'Success'
        except Exception as err:
            mess_out = "Error"
            current_app.logger.exception("Failure Modifying file! "+str(err))
    
    current_app.logger.info("Service File Modify ended")
    # return the message and data string as response
    return jsonify(message=mess_out, data=data_out)

'''
# API to rename a file
## This can be to rename a file
# Input: {'DocId':'', 'DocName':'', 'DocText':''}
# Processing: 
# 1. Authenticate user
# 2. Extract all input data 
# 3. Process the request:
# 3.a update the document name
# 3.b files does not have to be renamed
# 4. Output: UserId, DocId, DocName, FilePath
'''
@fileManagerBlueprint.route('/api/filerename', methods = ['GET', 'POST'])
@authentication
def file_Rename(user_id):
    current_app.logger.info("Service File Rename initiated")
    data_out = ''
    mess_out = ''

    if(request.method == 'POST'):
        # retrieve data inputs from the request
        content     = request.get_json(silent=True)
        userid      = user_id
        docid       = content['DocId']
        docname     = content['DocName']
        sql_stmt    = ''
        
        # open db connection
        session  = session_factory()
        
        try:
            if ((docid == 0) or (docid == '')):
                raise Exception('Document reference id not given. Cannot process!')
            
            # check if the document exists
            sql_stmt = select(Document.DocId).where(Document.DocId == docid)
            sql_result = session.execute(sql_stmt)
            noofrecords = len(sql_result.all())
            
            if (noofrecords == 0):
                raise Exception('Document reference id not found. Cannot rename!')
            else:

                file_paths_stmt = (select(DocumentHistory.FilePath).where(DocumentHistory.DocId==docid))
                file_paths = session.execute(file_paths_stmt).all()
                for path in file_paths:
                    path = path[0]
                    pattern = re.compile(r"/tmp/testdata/"+userid+r"/[a-zA-Z]+")
                    replacement = r"/tmp/testdata/"+userid+r"/"+docname
                    new_path = re.sub(pattern,replacement,path)
                    os.rename(path, new_path)
                    sql_stmt = sql_stmt = update(Document)\
                    .where(Document.DocId == docid)\
                    .values({Document.DocName:docname, Document.ModifiedDate:mod_date, Document.ModifiedBy:userid, Document.FilePath:new_path})
                    sql_stmt_2 = update (DocumentHistory)\
                        .where (DocumentHistory.DocId == docid)\
                            .values({DocumentHistory.DocName:docname, DocumentHistory.FilePath:new_path})
                    session.execute(sql_stmt)
                    session.execute(sql_stmt_2)
                    session.commit()
                    mod_date = datetime.today()
                    # update Documents table with the latest version
                    
                    
                    index = docname.index('.tex')
                    docname = docname[:index]
                    
                    userhist_entry = UserHistory(userid, docid, datetime.today(), docname, 'rename')
                    session.add(userhist_entry)
                    session.flush()
                    session.commit()
                    session.close()
                # building output data
                data_out = json.dumps({'UserId':userid, 'DocId':docid, 'DocName':docname})
                mess_out = 'Success'
        except Exception as err:
            mess_out = a
            current_app.logger.exception("Failure Renaming file! "+str(err))
    
    current_app.logger.info("Service File Rename ended")
    # return the message and data string as response
    return jsonify(message=mess_out, data=data_out)

'''
# API to get document list
## This can be to provide a list of documents for a user
# Input: {'UserId':''}
# Processing: 
# 1. Extract all input data 
# 2. Process the request:
# 3.a Get the list of active documents of the user
# 4. Output: UserId, DocumentList
'''
@fileManagerBlueprint.route('/api/filegetlist', methods = ['GET', 'POST'])
@authentication
def file_GetList(user_id):
    current_app.logger.info("Service Get Document List initiated")
    data_out = ''
    mess_out = ''
    docslist = []

    if(request.method == 'GET'):
        userid = user_id
        json_str = {}
    
        # open db connection
        session  = session_factory()
    
        try:
            # check if the document exists
            sql_stmt = select(Document.DocId, Document.DocName, Document.FilePath, Document.Version, Document.ModifiedDate, Document.ModifiedBy)\
                .where(Document.UserId == userid)
            sql_result = session.execute(sql_stmt) 
        
            for row in sql_result:
                json_str = {'DocId': row.DocId, \
                    'DocName':row.DocName , \
                    'FilePath': row.FilePath, \
                    'Version': row.Version, \
                    'LastModifiedOn': row.ModifiedDate, \
                    'LastModifiedBy': row.ModifiedBy}
                
                docslist.append(json_str)
            
            session.close()
            # json object with array of json documents list 
            data_out = json.dumps({'Documents': docslist})
            value={"message":"success"}
        except Exception as err:
            value={"message":"Error"}
            current_app.logger.exception("Failure getting the list of files! "+str(err))
    
    current_app.logger.info("Service Get Document List ended")
    # return the message and data string as response
    return make_response(jsonify(value, data_out))

@fileManagerBlueprint.route('/api/file/delete', methods=['GET', 'POST'])
@authentication
def file_delete(user_id):
    userid   = ''
    docid    = ''
    filename = ''
    data_out = ''
    mess_out = ''

    current_app.logger.info("Service file/delete initiated")
    if(request.method == 'POST'):
        content  = request.get_json(silent=True)
        userid   = user_id
        docid    = content['DocId']
        userperm = get_user_permissions(userid, docid)
        try:
            if 'W' in userperm:
                session = session_factory()
                file_paths_stmt = (select(DocumentHistory.FilePath) .where(DocumentHistory.docid == docid))
                file_paths = session.execute(file_paths_stmt).all()
                sql_stmt = delete(DocumentHistory).where (DocumentHistory.DocId == docid)
                sql_stmt_2 = delete(Document) .where(Document.DocId == docid)
                sql_stmt_3 = (select(Document.DocName).where(Document.DocId == docid))
                docname = session.execute(sql_stmt_3).first()[0]
                userhist_entry = UserHistory(userid, docid, datetime.today(), docname, 'delete')
                session.add(userhist_entry)
                session.flush()
                session.execute(sql_stmt)
                session.execute(sql_stmt_2)
                session.close()
                for file in file_paths:
                    if (os.path.exists(file)):
                        os.remove(file)
                    else:
                        current_app.logger.error("File does not exist at the path: ", file)
                mess_out='success'
            else:
                raise Exception("Access to delete denied!")
        except Exception:
            mess_out = 'fail'
            current_app.logger.exception("Failure deleting file!")
    current_app.logger.info("Service file/delete ended")
    return jsonify(message=mess_out)

@fileManagerBlueprint.route('/api/fileview', methods=['GET', 'POST'])
@authentication
def file_view(user_id):
    userid = user_id
    if request.method == "POST":
        content  = request.get_json(silent=True)
        docid   = content['DocId']
        userperm = get_user_permissions(userid, docid)
        try:
            if('W' in userperm):
                session = session_factory()
                sql_stmt = (select(Document.FilePath).where(Document.DocId==docid))
                result = session.execute(sql_stmt).first()
                session.close()

                file_path = result[0]
                with open(file_path,'r') as f:
                    data = f.read()
                data_out = {"file_content":data}
                return jsonify(data_out)
                print(data_out)
                
        except:
            print(x)
            return jsonify(message="error")
    return jsonify(message="Method not allowed")

@fileManagerBlueprint.route('/api/filetrash', methods = ['GET', 'POST'])
@authentication
def file_trash(user_id):
    current_app.logger.info("Service file/move to trash initiated")
    mess_out = ''
    
    if (request.method == 'POST'):
        content   = request.get_json(silent=True)
        userid = user_id
        docid     = content['DocId']
        try:
            userperm = get_user_permissions(userid, docid)
            if 'W' in userperm:
                session = session_factory()
                sql_stmt=update(Document).where(Document.DocId == docid) .values(IsTrash=1)
                sql_stmt_2 = update(DocumentHistory) .where(DocumentHistory.DocId == docid).values(IsTrash = 1)
                sql_stmt_3 = select()
                #("UPDATE Documents SET IsTrash=1 WHERE DocName = file_name,UserId=user_id")
                session.execute(sql_stmt)
                session.execute(sql_stmt_2)
                session.commit()
                session.close()
                mess_out = 'success'
            else:
                raise Exception("Permission to move to trash denied!")
            #return jsonify(message = "File moved to trash successfully")
        except Exception:
            #return jsonify(message='Oops! Something went wrong')
            mess_out = 'fail'
            current_app.logger.exception("Failure moving file to trash!")

    current_app.logger.info("Service file/move to trash ended")
    return jsonify(message=mess_out)

@fileManagerBlueprint.route('/api/fileretrive', methods = ['GET','POST'])
@authentication
def file_retrive(user_id):
    current_app.logger.info("Service file/retrieve from trash initiated")
    mess_out = ''
    if request.method == 'POST':
        content   = request.get_json(silent=True)
        userid    = user_id
        docid     = content['DocId']
        

        try:
            userperm = get_user_permissions(userid, docid)
            if 'W' in userperm:
                session = session_factory()
                sql_stmt=update(Document).where(Document.DocId == docid) .values(IsTrash=0)
                sql_stmt_2 = update(DocumentHistory) .where(DocumentHistory.DocId == docid).values(IsTrash = 0)
                session.execute(sql_stmt)
                session.execute(sql_stmt_2)
                session.commit()
                session.close()
                mess_out = 'success'
            else:
                raise Exception("Permission to retrieve from trash denied!")
            #return jsonify(message = "File moved to trash successfully")
        except Exception:
            #return jsonify(message='Oops! Something went wrong')
            mess_out = 'fail'
            current_app.logger.exception("Failure retrieving file from trash!")

    current_app.logger.info("Service file/retrieve from trash ended")
    return jsonify(message=mess_out)

@fileManagerBlueprint.route('/api/getTrashList', methods=["GET","POST"])
@authentication
def gettrashlist(user_id):
    userid = user_id
    mess_out = ''
    data_out = ''
    trashlist = []
    try:
        session = session_factory()
        sql_stmt = (select(Document.DocId, Document.DocName) .where(Document.UserId == userid, Document.IsTrash == 1))
        result = session.execute(sql_stmt)
        for row in result:
            json_str = {
                "DocId":row.DocId,
                "DocName":row.DocName
            }
            trashlist.append(json_str)
            data_out = json.dumps({'Documents': trashlist})
            mess_out = 'Success'
    except Exception:
        mess_out = 'Error'
        current_app.logger.exception("Failure getting the list of files! "+str(err))
    return jsonify(message=mess_out, data=data_out)