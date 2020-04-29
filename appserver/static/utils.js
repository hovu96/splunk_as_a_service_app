const appName = Splunk.util.getPath().match(`\/app\/(.+)\/.+`)[1];

define([
    'underscore',
    Splunk.util.make_url(`/static/app/${appName}/modal.js`),
], function (_, Modal) {
    return function () {
        const capitalize = (s) => {
            if (typeof s !== 'string') return ''
            return s.charAt(0).toUpperCase() + s.slice(1)
        }

        return {
            capitalize: capitalize,
            parseError: function (err) {
                var errorMessage;

                if (err.data && err.data.messages && err.data.messages.length > 0) {
                    errorMessage = err.data.messages.map(m => capitalize(m.text) + ".").join("\n ");
                } else if (err.data) {
                    errorMessage = err.data;
                } else if (err.error) {
                    errorMessage = err.error;
                } else if (err.status) {
                    errorMessage = '' + err.status;
                } else {
                    errorMessage = '' + err;
                }

                return errorMessage;
            },
            makeid: function (length) {
                var result = '';
                var characters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';
                var charactersLength = characters.length;
                for (var i = 0; i < length; i++) {
                    result += characters.charAt(Math.floor(Math.random() * charactersLength));
                }
                return result;
            },
            newLoadingIndicator(options) {
                options = _.extend({
                    title: "Loading...",
                    subtitle: "Please wait.",
                }, options);
                const modal = new Modal(this.makeid(30), {
                    title: options.title,
                    backdrop: 'static',
                    keyboard: false,
                    destroyOnHide: true,
                    type: 'normal',
                    center: true,
                });
                modal.body.append($('<p></p>').text(options.subtitle));
                $(".modal-body", modal.$el).css("padding-bottom", "10px");
                modal.show();
                return modal;
            },
            showErrorDialog(title, err, button) {
                if (title == null || title == undefined || title == "") {
                    title = "Error Occurred";
                }
                const errorText = this.parseError(err);
                const modal = new Modal(this.makeid(30), {
                    title: title,
                    backdrop: 'static',
                    keyboard: false,
                    destroyOnHide: true,
                    type: 'normal',
                    button: button,
                });
                const encode = function (str) {
                    var buf = [];
                    for (var i = str.length - 1; i >= 0; i--) {
                        buf.unshift(['&#', str[i].charCodeAt(), ';'].join(''));
                    }
                    return buf.join('');
                }
                modal.body.append($('<p>' + encode(errorText) + '</p>'));
                modal.show();
                return modal;
            },
            normalizeBoolean: function (test, strictMode) {
                if (typeof (test) == 'string') {
                    test = test.toLowerCase();
                }
                switch (test) {
                    case true:
                    case 1:
                    case '1':
                    case 'yes':
                    case 'on':
                    case 'true':
                        return true;
                    case false:
                    case 0:
                    case '0':
                    case 'no':
                    case 'off':
                    case 'false':
                        return false;
                    default:
                        if (strictMode) throw TypeError("Unable to cast value into boolean: " + test);
                        return test;
                }
            },
            createRestEndpoint: function () {
                const http = new splunkjs.SplunkWebHttp();
                const service = new splunkjs.Service(http, {
                    owner: "nobody",
                    app: appName,
                    sharing: "app",
                });
                var endpoint = new splunkjs.Service.Endpoint(service, "saas");
                endpoint.getAsync = function (path, options) {
                    return new Promise((resolve, reject) => {
                        this.get(path, options, function (err, response) {
                            if (err) {
                                reject(err);
                                return;
                            }
                            resolve(response);
                        });
                    });
                };
                endpoint.postAsync = function (path, options) {
                    return new Promise((resolve, reject) => {
                        this.post(path, options, function (err, response) {
                            if (err) {
                                reject(err);
                                return;
                            }
                            resolve(response);
                        });
                    });
                };
                endpoint.delAsync = function (path, options) {
                    return new Promise((resolve, reject) => {
                        this.del(path, options, function (err, response) {
                            if (err) {
                                reject(err);
                                return;
                            }
                            resolve(response);
                        });
                    });
                };
                return endpoint;
            },
            to: function (promise) {
                return promise.then(function (result) {
                    return [result, undefined];
                }).catch(function (err) {
                    return [undefined, err];
                });
            },
            getResponseContents: function (response) {
                return new Promise((resolve, reject) => {
                    if (!response.data) {
                        reject("Unexpected response format (missing 'data')")
                        return;
                    }
                    if (!response.data.entry) {
                        reject("Unexpected response format (missing 'data.entry')")
                        return;
                    }
                    const contents = response.data.entry.map(function (e) {
                        return e.content;
                    });
                    resolve(contents);
                });
            },
            getResponseContent: async function (response) {
                const contents = await this.getResponseContents(response);
                const content = await new Promise((resolve, reject) => {
                    if (contents.length == 0) {
                        reject("response has no content")
                        return;
                    }
                    if (contents.length > 1) {
                        reject("response multiple contents")
                        return;
                    }
                    resolve(contents[0]);
                });
                return content;
            },
        };
    }();
});