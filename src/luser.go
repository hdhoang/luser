package main

import (
	"bufio"
	"flag"
	"fmt"
	irc "github.com/fluffle/goirc/client"
	"github.com/fluffle/goirc/logging/glog"
	"golang.org/x/net/html"
	"os"
	"strings"
	"net/http"
	"io/ioutil"
	"compress/gzip"
	"io"
	"bytes"
	"net/url"
	log "github.com/cihub/seelog"
	"github.com/jmoiron/jsonq"
	"runtime"
	"regexp"
	"encoding/json"
)
type Message struct {
	Name, Text string
}
var host *string = flag.String("host", "irc.freenode.net", "IRC server")
var channel *string = flag.String("channel", "#hungtest", "IRC channel")

func postSource() string {
	_, filename, _, _ := runtime.Caller(1)
	content, err := ioutil.ReadFile(filename)
	data := url.Values{}
	data.Set("f:1", string(content))
	data.Add("name:1", "luser.go")
	data.Add("read:1", "2")

	if err != nil {
		log.Error("Error reading source file", filename)
	}

	client := new(http.Client)
	// bytes.NewBufferString(data)
	request, err := http.NewRequest("POST", "http://ix.io", bytes.NewBufferString(data.Encode()))
	resp, err := client.Do(request)

	if err != nil {
		log.Error("Cannot post source code", err)
	}

	defer resp.Body.Close()
	u, _ := ioutil.ReadAll(resp.Body)
	return strings.TrimSpace(string(u))
}

func google(text string) string {
	var Url *url.URL
	result := "No Result"
	Url, _ = url.Parse("https://ajax.googleapis.com")
	Url.Path += "/ajax/services/search/web"
	parameters := url.Values{}
	parameters.Add("v", "1.0")
	parameters.Add("rsz", "1")
	parameters.Add("q", text)
	Url.RawQuery = parameters.Encode()
	client := new(http.Client)
	request, err := http.NewRequest("GET", Url.String(), nil)
	request.Header.Add("User-Agent", "Mozilla/5.0")
	if err != nil {
		log.Error("Cannot make request to google api", err)
		return result
	}
	resp, err := client.Do(request)
	if err != nil {
		log.Error("Cannot get response from google api", err)
		return result
	}
	dec := json.NewDecoder(resp.Body)
	data := map[string]interface{}{}
	dec.Decode(&data)
	jq := jsonq.NewQuery(data)
	title, _ := jq.String("responseData", "results", "0", "titleNoFormatting")
	resultUrl, _ := jq.String("responseData", "results", "0", "url")
	return title + " " + resultUrl
}

func title(url string) string {
	client := new(http.Client)
	request, err := http.NewRequest("GET", url, nil)
	request.Header.Add("Accept-Encoding", "gzip, deflate, sdch")
	request.Header.Add("User-Agent", "Mozilla/5.0")
	resp, err := client.Do(request)
	urlTitle := "No fucking title found"

	if err != nil {
		log.Debug(err)
		return urlTitle
	} 

	if resp.StatusCode == 200  {
		if strings.Contains(resp.Header["Content-Type"][0], "text/html") {
			var buffer io.Reader
			defer resp.Body.Close()
			
			if resp.Header.Get("Content-Encoding") == "gzip" {
				buffer, err = gzip.NewReader(resp.Body)
				if err != nil {
					log.Debug("Error getting title", err)
					return urlTitle
				}
			} else {
				buffer = resp.Body
			}

			content, err := ioutil.ReadAll(io.LimitReader(buffer, 1<<18))

			if err != nil {
				log.Debug("Error getting title", err)
				return urlTitle
			}

			d := html.NewTokenizer(strings.NewReader(string(content)))

			for {

		        tokenType := d.Next()
		        if tokenType == html.ErrorToken {
		            return urlTitle
		        }
		        token := d.Token()
		        if tokenType == html.StartTagToken {
		            if strings.ToLower(token.Data) == "title" {
		                tokenType := d.Next()
		                if tokenType == html.TextToken {
		                    return strings.TrimSpace(d.Token().Data)
		                }
					}
				}
			}
		}
	}
    return urlTitle 
}

func setupLogger() {
    Config := `
    <seelog type="sync">
		<outputs formatid="main">
			<console/>
		</outputs>
		<formats>
			<format id="main" format="%Date/%Time [%LEV] %Msg%n"/>
		</formats>
	</seelog>`
    logger, err := log.LoggerFromConfigAsBytes([]byte(Config))

    if err != nil {
        log.Debug(err)
        return
    }
    log.ReplaceLogger(logger)
    return
}


func main() {
	flag.Parse()
	glog.Init()
	setupLogger()
	c := irc.SimpleClient("sumthing", "gobo")
	c.EnableStateTracking()
	c.HandleFunc("connected", func(conn *irc.Conn, line *irc.Line) { 
			conn.Join(*channel) 
			log.Debug("Connected to server!")
	})
	urlRegex := regexp.MustCompile(`(https?)://([\w_-]+(?:(?:\.[\w_-]+)+))([\w.,@?^=%&:/~+#-]*[\w@?^=%&/~+#-])`)
	quit := make(chan bool)
	c.HandleFunc("disconnected",
		func(conn *irc.Conn, line *irc.Line) { quit <- true })

	c.HandleFunc("PRIVMSG",
		func (conn *irc.Conn, line *irc.Line) {
			url := urlRegex.FindString(line.Args[1])
			if  url != "" {
				urlTitle := title(url)
				conn.Privmsg(line.Args[0], urlTitle)
			} else if strings.TrimSpace(line.Args[1]) == ".report" {
				conn.Privmsg(line.Args[0], "operate by " + os.Getenv("USER") + ", Source code: " + postSource())
			} else if strings.HasPrefix(line.Args[1], ".g ") {
				conn.Privmsg(line.Args[0], google(line.Args[1][2:]))
			}
		})
	// set up a goroutine to read commands from stdin
	in := make(chan string, 4)
	reallyquit := false

	go func() {
		con := bufio.NewReader(os.Stdin)
		for {
			s, err := con.ReadString('\n')
			if err != nil {
				close(in)
				break
			}
			// no point in sending empty lines down the channel
			if len(s) > 2 {
				in <- s[0 : len(s)-1]
			}
		}
	}()

	// set up a goroutine to do parsey things with the stuff from stdin
	go func() {
		for cmd := range in {
			if cmd[0] == ':' {
				switch idx := strings.Index(cmd, " "); {
					case cmd[1] == 'd':
						fmt.Printf(c.String())
					case cmd[1] == 'f':
						if len(cmd) > 2 && cmd[2] == 'e' {
							// enable flooding
							c.Config().Flood = true
						} else if len(cmd) > 2 && cmd[2] == 'd' {
							// disable flooding
							c.Config().Flood = false
						}
						for i := 0; i < 20; i++ {
							c.Privmsg("#", "flood test!")
						}
					case idx == -1:
						continue
					case cmd[1] == 'q':
						reallyquit = true
						c.Quit(cmd[idx+1 : len(cmd)])
					case cmd[1] == 'j':
						c.Join(cmd[idx+1 : len(cmd)])
					case cmd[1] == 'p':
						c.Part(cmd[idx+1 : len(cmd)])
				}
			} else {
				c.Raw(cmd)
			}
		}
	}()

	for !reallyquit {
		// connect to server
		if err := c.ConnectTo(*host); err != nil {
			fmt.Printf("Connection error: %s\n", err)
			return
		}

		// wait on quit channel
		<-quit
	}
}
